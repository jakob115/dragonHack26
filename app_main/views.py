from decimal import Decimal, InvalidOperation
from io import BytesIO

from django.db.models import Q
from django.db.models.aggregates import Sum
from django.http import JsonResponse, HttpResponse, StreamingHttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
import calendar
from datetime import datetime, timedelta
from bson import ObjectId
from google.genai import types
from google import genai

from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.core.serializers.json import DjangoJSONEncoder
from .models import ReceiptTransaction, Category, ItemTransaction, Account, IncomeTransaction, ScheduleExpense, Budget

from .tasks import receipt_image_background_process

from DH26 import settings

import json
import pandas

client = genai.Client(api_key=settings.GEMINI_API_KEY)


def _savings_rate_pct(income: Decimal, expenses: Decimal):
    """Portion of income not spent this period; None if income is zero."""
    if income <= 0:
        return None
    saved = income - expenses
    return float((saved / income * Decimal("100")).quantize(Decimal("0.01")))


def _recurring_monthly_equivalent(user):
    """Approximate total monthly outflow from scheduled expenses (normalized by cadence)."""
    total = Decimal("0")
    for row in ScheduleExpense.objects.filter(user=user):
        cost = row.cost or Decimal("0")
        if row.type == "DAILY":
            total += cost * Decimal("30")
        elif row.type == "WEEKLY":
            total += cost * (Decimal("52") / Decimal("12"))
        elif row.type == "MONTHLY":
            total += cost
        elif row.type == "YEARLY":
            total += cost / Decimal("12")
    return total.quantize(Decimal("0.01"))


# Create your views here.
@login_required
def home(request):
    context = {"active_page": "dashboard"}
    balance = Account.objects.filter(user=request.user).aggregate(Sum('balance'))['balance__sum'] or 0
    s_balance = "{:.2f}".format(balance)
    int_part, dec_part = s_balance.split('.')
    context['net_worth_int'] = int_part
    context['net_worth_dec'] = dec_part
    context['accounts_count'] = Account.objects.filter(user=request.user).count()
    context['balance'] = balance
    context['reccuring_expenses'] = ScheduleExpense.objects.filter(user=request.user)
    context['latest_transactions'] = ItemTransaction.objects.filter(user=request.user).order_by("-id")[:3]
    context['next_recurring'] = ScheduleExpense.objects.filter(user=request.user).order_by("-id")[:1]
    context['flagged_count'] = ItemTransaction.objects.filter(account__isnull=True).count()
    budget_agg = Budget.objects.filter(user=request.user).aggregate(
        total_balance=Sum("balance"),
        total_limit=Sum("limit"),
    )
    total_budget_balance = budget_agg["total_balance"] or Decimal("0")
    total_budget_limit = budget_agg["total_limit"] or Decimal("0")
    if total_budget_limit > 0:
        used_ratio = total_budget_balance / total_budget_limit
        budget_health_pct = float(min(used_ratio * 100, Decimal("100")))
    else:
        budget_health_pct = 0.0
    budget_remaining = total_budget_limit - total_budget_balance
    context["budget_health_pct"] = round(budget_health_pct, 1)
    context["budget_over"] = budget_remaining < 0
    context["has_budgets"] = Budget.objects.filter(user=request.user).exists()
    context["budget_has_limits"] = total_budget_limit > 0
    context["budget_remaining_abs"] = abs(budget_remaining)

    today = timezone.localdate()
    month_start = today.replace(day=1)
    last_day = calendar.monthrange(today.year, today.month)[1]
    month_end = today.replace(day=last_day)
    income_qs = IncomeTransaction.objects.filter(
        user=request.user,
        date__gte=month_start,
        date__lte=month_end,
    )
    income_mtd_raw = income_qs.aggregate(total=Sum("amount"))["total"]
    income_mtd = (income_mtd_raw or Decimal("0")).quantize(Decimal("0.01"))
    context["income_mtd"] = income_mtd
    context["income_count"] = income_qs.count()
    context["income_latest"] = income_qs.order_by("-date", "-id").first()

    expenses_mtd_raw = (
        ItemTransaction.objects.filter(
            user=request.user,
            date__gte=month_start,
            date__lte=month_end,
        ).aggregate(total=Sum("cost"))["total"]
    )
    expenses_mtd = (expenses_mtd_raw or Decimal("0")).quantize(Decimal("0.01"))
    context["expenses_mtd"] = expenses_mtd
    context["monthly_burn"] = expenses_mtd

    prev_month_end = month_start - timedelta(days=1)
    prev_month_start = prev_month_end.replace(day=1)
    expenses_prev_raw = (
        ItemTransaction.objects.filter(
            user=request.user,
            date__gte=prev_month_start,
            date__lte=prev_month_end,
        ).aggregate(total=Sum("cost"))["total"]
    )
    expenses_prev = (expenses_prev_raw or Decimal("0")).quantize(Decimal("0.01"))
    context["expenses_prev_month"] = expenses_prev

    income_prev_raw = (
        IncomeTransaction.objects.filter(
            user=request.user,
            date__gte=prev_month_start,
            date__lte=prev_month_end,
        ).aggregate(total=Sum("amount"))["total"]
    )
    income_prev = (income_prev_raw or Decimal("0")).quantize(Decimal("0.01"))

    saved_mtd = (income_mtd - expenses_mtd).quantize(Decimal("0.01"))
    context["saved_mtd"] = saved_mtd
    context["saved_mtd_negative"] = saved_mtd < 0
    context["saved_mtd_abs"] = abs(saved_mtd).quantize(Decimal("0.01"))

    savings_rate = _savings_rate_pct(income_mtd, expenses_mtd)
    savings_rate_prev = _savings_rate_pct(income_prev, expenses_prev)
    context["savings_rate_pct"] = savings_rate
    context["savings_rate_delta_pp"] = (
        round(savings_rate - savings_rate_prev, 2)
        if savings_rate is not None and savings_rate_prev is not None
        else None
    )

    recurring_qs = ScheduleExpense.objects.filter(user=request.user)
    context["recurring_monthly_total"] = _recurring_monthly_equivalent(request.user)
    context["recurring_active_count"] = recurring_qs.count()

    context["dashboard_month_label"] = today.strftime("%B %Y")

    context['recurring_expenses'] = recurring_qs
    return render(request, 'home.html', context)


@login_required
def delete_transaction_receipt(request, receipt_id):
    object_id = ObjectId(receipt_id)
    receipt = ReceiptTransaction.objects.get(id=object_id)
    receipt.delete()
    return redirect("transactions")

@login_required
def delete_transaction_item(request, item_id):
    object_id = ObjectId(item_id)
    item = ItemTransaction.objects.get(id=object_id)
    item.delete()
    return redirect("transactions")

@login_required
def edit_transaction_item(request, item_id):
    object_id = ObjectId(item_id)
    item = ItemTransaction.objects.get(id=object_id)
    request.session["editing_item_id"] = item_id
    return render(request, 'edit_item.html', {"active_page": "edit_item",
                                              "item": item,
                                              })

@login_required
def edit_item(request):

    item_id = request.session.get("editing_item_id")
    if not item_id:
        return redirect("transactions")
    object_id = ObjectId(item_id)
    item = ItemTransaction.objects.get(id=object_id)

    new_name = request.POST.get("name")
    new_merchant = request.POST.get("merchant")
    new_cost = request.POST.get("cost")
    new_quantity = request.POST.get("quantity")
    new_category = request.POST.get("category")
    new_date = request.POST.get("date")

    if new_name is not None:
        item.name = new_name
    if new_merchant is not None:
        item.merchant = new_merchant
    if new_cost is not None:
        item.cost = new_cost
    if new_quantity is not None:
        item.quantity = new_quantity
    if new_category:
        item.category = Category.objects.get(title=new_category)
    if new_date:
        item.date = new_date

    item.save()
    del request.session["editing_item_id"]
    return redirect("transactions")



@login_required
def transactions(request):
    context = {}
    context['active_page'] = "transactions"
    curr_user = request.user

    transaction_data = []
    receipts = ReceiptTransaction.objects.filter(user=curr_user)
    for receipt in receipts:
        linked_items = receipt.itemtransaction_set.all()
        if linked_items:
            receipt_date = linked_items[0].date
            receipt_merchat = linked_items[0].merchant

            transaction_data.append({'transaction_date':receipt_date, 'transaction_merchant': receipt_merchat, 'item_list': linked_items, 'receipt_id': str(receipt.id)})

    items = ItemTransaction.objects.filter(user=curr_user, receipt=None)

    for item in items:
        transaction_data.append({'transaction_date':item.date, 'item': item })

    transaction_data.sort(key=lambda x: x["transaction_date"], reverse=True)

    context['transaction_data'] = transaction_data
    return render(request, 'transactions.html', context)


@login_required
def recurring(request):
    context = {}
    context['active_page'] = "recurring"
    types = ScheduleExpense.TYPE_OF_EXPENSE
    context['expense_types'] = types
    curr_user = request.user
    context['accounts'] = Account.objects.filter(user=curr_user)
    recurring_expenses = ScheduleExpense.objects.filter(user=curr_user)

    context['recurring_expenses'] = recurring_expenses
    return render(request, 'recurring.html', context)


@login_required
def create_recurring_item(request):
    return render(request, 'create_recurring.html', {"active_page": "create_recurring"})


@login_required
def create_recurring(request):
    if request.method != "POST":
        return redirect("recurring")

    recurring_user = request.user
    recurring_title = request.POST.get("title") or ""
    recurring_cost_raw = request.POST.get("cost") or ""
    recurring_type = request.POST.get("type") or ""
    recurring_account_id = request.POST.get("account") or ""
    recurring_account = None
    valid_types = {choice[0] for choice in ScheduleExpense.TYPE_OF_EXPENSE}

    if not recurring_title or not recurring_cost_raw or recurring_type not in valid_types:
        return redirect("recurring")

    try:
        recurring_cost = Decimal(str(recurring_cost_raw).strip().replace(",", "."))
    except (InvalidOperation, TypeError, ValueError):
        return redirect("recurring")

    if recurring_cost <= 0:
        return redirect("recurring")

    if recurring_account_id:
        recurring_account = get_object_or_404(Account, pk=recurring_account_id, user=recurring_user)

    ScheduleExpense.objects.create(
        user=recurring_user,
        title=recurring_title,
        cost=recurring_cost,
        type=recurring_type,
        account=recurring_account,
    )
    return redirect("recurring")



@login_required
def delete_recurring_item(request, rec_id):
    if request.method not in {"POST", "GET"}:
        return redirect("recurring")

    rec = get_object_or_404(ScheduleExpense, pk=rec_id, user=request.user)
    rec.delete()
    return redirect("recurring")

@login_required
def edit_recurring_item(request, rec_id):
    rec = get_object_or_404(ScheduleExpense, pk=rec_id, user=request.user)
    request.session["editing_recurring_id"] = rec_id
    return render(
        request,
        'edit_recurring.html',
        {
            "active_page": "recurring",
            "rec": rec,
            "accounts": Account.objects.filter(user=request.user),
            "expense_types": ScheduleExpense.TYPE_OF_EXPENSE,
        },
    )

@login_required
def edit_recurring(request):
    rec_id = request.session.get("editing_recurring_id")
    if not rec_id:
        return redirect("recurring")
    if request.method != "POST":
        return redirect("edit_recurring_item", rec_id=rec_id)

    rec = get_object_or_404(ScheduleExpense, pk=rec_id, user=request.user)

    new_title = request.POST.get("title")
    new_cost = request.POST.get("cost")
    new_type = request.POST.get("type")
    new_account_id = request.POST.get("account")
    new_account = None

    if new_account_id:
        new_account = get_object_or_404(Account, pk=new_account_id, user=request.user)

    if new_title is not None:
        rec.title = new_title
    if new_cost is not None:
        rec.cost = new_cost
    if new_type is not None:
        rec.type = new_type
    if new_account_id is not None:
        rec.account = new_account

    rec.save()
    del request.session["editing_recurring_id"]

    return redirect("recurring")


@login_required
def delete_budget_item(request, budget_id):
    if request.method not in {"POST", "GET"}:
        return redirect("budgets")

    budget = get_object_or_404(Budget, pk=budget_id, user=request.user)
    budget.delete()

    return redirect("budgets")


@login_required
def analytics(request):
    return render(request, 'analytics.html', {"active_page": "analytics"})


@login_required
def budgets(request):
    context = {"active_page": "budgets"}
    categories = Category.objects.all().order_by("title")
    budgets = Budget.objects.filter(user=request.user).select_related("category").order_by("title")
    context['categories'] = categories
    context['budgets'] = budgets
    return render(
        request,
        "budgets.html",
        context,
    )


def _category_and_descendant_ids(category):
    """PKs of this category and every nested subcategory (recursive children)."""
    ids = [category.pk]
    for child in Category.objects.filter(parent=category):
        ids.extend(_category_and_descendant_ids(child))
    return ids

@login_required
def add_budget(request):
    if request.method != "POST":
        return redirect("budgets")
    title = request.POST.get("title") or ""
    limit_raw = request.POST.get("limit") or ""
    category_id = request.POST.get("category") or ""
    if not title or limit_raw in (None, "") or not category_id:
        return redirect("budgets")
    try:
        limit_val = Decimal(str(limit_raw).strip().replace(",", "."))
    except (InvalidOperation, TypeError, ValueError):
        return redirect("budgets")
    if limit_val <= 0:
        return redirect("budgets")
    try:
        cat = Category.objects.get(pk=category_id)
    except Category.DoesNotExist:
        return redirect("budgets")

    # Same calendar month as today (user's active timezone).
    # Include: this category + all subcategories (recursive), plus any Category row with the same title (not id).
    today = timezone.localdate()
    month_start = today.replace(day=1)
    last_day = calendar.monthrange(today.year, today.month)[1]
    month_end = today.replace(day=last_day)

    tree_ids = _category_and_descendant_ids(cat)
    title_ids = Category.objects.filter(title=cat.title).values_list("pk", flat=True)
    category_ids = list(set(tree_ids) | set(title_ids))

    spent = (
        ItemTransaction.objects.filter(
            user=request.user,
            date__gte=month_start,
            date__lte=month_end,
        )
        .filter(
            Q(category_id__in=category_ids)
            | Q(subcategory_id__in=category_ids)
        )
        .aggregate(total=Sum("cost"))["total"]
    )
    balance_val = Decimal(str(spent)) if spent is not None else Decimal("0.00")
    balance_val = balance_val.quantize(Decimal("0.01"))

    Budget.objects.create(
        user=request.user,
        title=title,
        limit=limit_val,
        balance=balance_val,
        category=cat,
    )

    return redirect("budgets")


@login_required
def chat(request):
    context = {"active_page": "chat"}
    return render(request, "chat.html", context)


def _chat_transactions_payload(request):
    """Recent item transactions for this user (JSON-serializable)."""
    qs = (
        ItemTransaction.objects.filter(user=request.user)
        .select_related("category")
        .order_by("-date")[:250]
        .values(
            "name",
            "merchant",
            "cost",
            "quantity",
            "date",
            "category__title",
        )
    )
    return json.loads(json.dumps(list(qs), cls=DjangoJSONEncoder))


def _build_chat_system_instruction(request, insight_mode=False):
    tx_json = _chat_transactions_payload(request)
    tx_blob = json.dumps(tx_json, indent=2, cls=DjangoJSONEncoder)

    # Do not use an f-string for the whole prompt: JSON may contain "{" / "}" and break parsing.
    base = (
        "You are Ledger AI, a concise assistant inside a personal budgeting and expense-tracking web app.\n\n"
        "## Output format (required)\n"
        "The chat UI renders your reply as **GitHub-flavored Markdown** (then sanitized). Use Markdown for structure and emphasis:\n"
        "- Headings: `##` / `###` for sections\n"
        "- **Bold** and *italics* for emphasis\n"
        "- Bullet lists with `-` and numbered lists with `1.`\n"
        "- Short tables when comparing numbers (Markdown tables)\n"
        "- Inline `code` for merchant names, categories, or formulas\n\n"
        "Prefer Markdown over raw HTML.\n\n"
        "## Charts and graphs (when helpful)\n"
        "When a chart would help (trends, category splits, comparisons), add a **Mermaid** diagram in a fenced block, for example:\n\n"
        "```mermaid\n"
        "pie title Spending by category\n"
        '  "Groceries" : 706\n'
        '  "Transport" : 274\n'
        "```\n\n"
        "Use valid Mermaid syntax (`flowchart`, `pie`, `xychart-beta`, etc.). Keep diagrams small. "
        "If a diagram might not parse, use a Markdown table instead.\n\n"
        "## Safety\n"
        "- Never output `<script>`, event handlers, or `javascript:` URLs.\n"
        "- Do not claim you executed code or accessed live accounts beyond the JSON context below.\n\n"
        "## User transaction context (JSON, up to 250 recent rows)\n"
        "```json\n"
        + tx_blob
        + "\n```\n\n"
        "Use amounts and categories from this data when answering. If the list is empty, say you have no saved "
        "transactions yet and suggest how to add them."
    )
    if insight_mode:
        base += (
            "\n\n## This request (dashboard insight only)\n"
            "Respond with **only** a short insight: 2–4 sentences, actionable, plain language. "
            "No section headings (`##`), no Mermaid diagrams, no tables. "
            "Use **bold** sparingly for key numbers or category names."
        )
    return base


DEFAULT_DASHBOARD_INSIGHT_MESSAGE = (
    "Give a short AI insight about my spending using only the transaction JSON in your context. "
    "2–4 sentences, actionable, plain language. Use **bold** sparingly for key numbers or categories."
)


def _analytics_payload_for_llm(request):
    """Structured snapshot for analytics / chart prompts (JSON-safe primitives)."""
    user = request.user
    items = []
    for row in (
        ItemTransaction.objects.filter(user=user)
        .select_related("category", "subcategory", "receipt", "budget")
        .order_by("-date")[:400]
    ):
        items.append(
            {
                "date": row.date.strftime("%Y-%m-%d") if row.date else "",
                "name": row.name or "",
                "merchant": row.merchant or "",
                "cost": str(row.cost),
                "quantity": str(row.quantity),
                "category": row.category.title if row.category_id else "",
                "subcategory": row.subcategory.title if row.subcategory_id else "",
                "receipt_id": str(row.receipt_id) if row.receipt_id else "",
                "budget_title": row.budget.title if row.budget_id else "",
            }
        )

    receipts = []
    for r in ReceiptTransaction.objects.filter(user=user).order_by("-id")[:100]:
        item_count = r.itemtransaction_set.count()
        receipts.append(
            {
                "id": str(r.pk),
                "title": r.title or "",
                "linked_item_transaction_count": item_count,
            }
        )

    income_rows = []
    for inc in IncomeTransaction.objects.filter(user=user).order_by("-date", "-id")[:150]:
        income_rows.append(
            {
                "amount": str(inc.amount),
                "type": inc.type,
                "description": inc.description or "",
                "date": inc.date.strftime("%Y-%m-%d") if inc.date else "",
            }
        )

    budgets = []
    for b in Budget.objects.filter(user=user).select_related("category"):
        budgets.append(
            {
                "title": b.title,
                "balance": str(b.balance),
                "limit": str(b.limit),
                "category": b.category.title if b.category_id else "",
                "percent_used": str(b.percentage),
            }
        )

    recurring = []
    for s in ScheduleExpense.objects.filter(user=user).select_related("account"):
        recurring.append(
            {
                "title": s.title,
                "cost": str(s.cost),
                "cadence": s.get_type_display(),
                "cadence_code": s.type,
                "account": s.account.title if s.account_id else "",
            }
        )

    return {
        "item_transactions": items,
        "receipts": receipts,
        "income_transactions": income_rows,
        "budgets": budgets,
        "recurring_transactions": recurring,
    }


def _build_analytics_chart_system_instruction(request, chart_slot: int) -> str:
    payload = _analytics_payload_for_llm(request)
    blob = json.dumps(payload, indent=2, cls=DjangoJSONEncoder)
    header = (
        "You are Ledger AI helping on the user's **Analytics** page.\n"
        "All numbers and claims must be grounded in the JSON below (aggregate, sum, or compare windows).\n\n"
        "## Full ledger snapshot (JSON)\n"
        "```json\n"
        + blob
        + "\n```\n\n"
    )
    if chart_slot == 1:
        body = (
            "## Chart panel A (spending)\n"
            "Output format (**strict**):\n"
            "1. First line: a Markdown `###` heading (max 8 words) describing the chart.\n"
            "2. Next: **exactly one** fenced Mermaid block: ```mermaid … ``` with valid syntax.\n"
            "3. **Stop** after the closing ``` — no tables, no second diagram, no extra paragraphs.\n\n"
            "**Focus:** `item_transactions` — category and/or merchant mix, or time buckets (week/month). "
            "You may use `receipts` / `receipt_id` only to enrich (e.g. receipts with many line items).\n"
            "**Prefer:** `pie title …` or `xychart-beta` for numeric series.\n"
        )
    elif chart_slot == 2:
        body = (
            "## Chart panel B (income, budgets, recurring)\n"
            "Same **strict** format as panel A: `###` title, then **one** ```mermaid block, then stop.\n\n"
            "**Focus:** `income_transactions`, `budgets` (spent/balance vs limit), and `recurring_transactions`. "
            "You may contrast recurring monthly load vs a simple total from item spend when data allows.\n"
            "**Do not** produce a plain category pie chart (that is panel A). "
            "**Prefer:** `xychart-beta` (e.g. budget limit vs spent), `flowchart LR`, or bar-like xychart comparisons.\n"
        )
    elif chart_slot == 3:
        body = (
            "## Panel C — Cut costs, spot increases, tips\n"
            "Output **GitHub-flavored Markdown** (no raw HTML). Structure:\n"
            "1. `##` title (max 10 words) about minimizing expenses / where spend grew.\n"
            "2. A short section (2–5 sentences) explaining **where spending increased** using `item_transactions` dates: "
            "prefer **last 30 calendar days vs the previous 30 days** (sum `cost` per category or merchant). "
            "If there are too few days of data, compare **this calendar month to date vs the same-length prefix of last month** "
            "or state clearly that the sample is thin.\n"
            "3. `### Practical tips` followed by a **bullet list** (4–7 items) of concrete ways to reduce spend, "
            "each tied when possible to their categories, merchants, `budgets`, or `recurring_transactions`.\n"
            "4. **Exactly one** fenced Mermaid block ```mermaid … ``` that visualizes **increases or hot spots** "
            "(e.g. `xychart-beta` with two series “prior window” vs “recent window” for top categories, or a bar-style comparison). "
            "Do **not** add a second Mermaid block.\n"
            "5. After the Mermaid block, at most **2 short sentences** closing encouragement — no extra diagrams.\n\n"
            "Tone: supportive, specific, actionable. Use **bold** for key euro amounts and category names.\n"
        )
    elif chart_slot == 4:
        body = (
            "## Panel D — Income only (narrative + chart)\n"
            "Use **only** `income_transactions` from the JSON for numbers and trends (do not discuss expense categories or item spend). "
            "Output **GitHub-flavored Markdown** (no raw HTML). Structure:\n"
            "1. `##` title (max 10 words) about their **income** picture (e.g. stability, mix, momentum).\n"
            "2. A short section (2–5 sentences) on **how income changed**: prefer **last 30 calendar days vs the previous 30 days** "
            "(sum `amount` overall and, if useful, by `type`). If data is thin, say so and use the best window you can "
            "(e.g. this month vs last month).\n"
            "3. `### Ideas to grow or stabilize income` followed by a **bullet list** (4–7 items) grounded in their `type` "
            "labels, amounts, and patterns (diversification, timing, record-keeping, etc.).\n"
            "4. **Exactly one** fenced Mermaid block ```mermaid … ``` visualizing income (e.g. `pie` by `type`, "
            "`xychart-beta` comparing the two windows, or `flowchart LR` for income streams). "
            "Do **not** add a second Mermaid block.\n"
            "5. After the Mermaid block, at most **2 short sentences** — no extra diagrams.\n\n"
            "Use **bold** for key euro totals and income `type` names.\n"
        )
    else:
        body = (
            "## Chart panel A (spending)\n"
            "Output format (**strict**):\n"
            "1. First line: a Markdown `###` heading (max 8 words) describing the chart.\n"
            "2. Next: **exactly one** fenced Mermaid block: ```mermaid … ``` with valid syntax.\n"
            "3. **Stop** after the closing ``` — no tables, no second diagram, no extra paragraphs.\n\n"
            "**Focus:** `item_transactions` — category and/or merchant mix, or time buckets (week/month).\n"
        )
    if chart_slot == 3:
        footer = (
            "## Sparse data\n"
            "If `item_transactions` is empty or nearly empty, say so briefly, give generic savings habits, "
            "and still include one tiny valid Mermaid diagram (e.g. one node “Add transactions”).\n\n"
            "## Safety\n"
            "No `<script>`, no raw HTML outside Markdown/Mermaid.\n"
        )
    elif chart_slot == 4:
        footer = (
            "## Sparse data\n"
            "If `income_transactions` is empty or nearly empty, say so briefly, suggest logging income entries, "
            "and still include one tiny valid Mermaid diagram (e.g. one node “Add income”).\n\n"
            "## Safety\n"
            "No `<script>`, no raw HTML outside Markdown/Mermaid.\n"
        )
    else:
        footer = (
            "## Sparse data\n"
            "If lists are empty, emit a minimal valid Mermaid diagram titled e.g. `No data yet` with one placeholder node "
            "or pie slice explaining what to add.\n\n"
            "## Safety\n"
            "No `<script>`, no raw HTML outside Markdown/Mermaid.\n"
        )
    return header + body + footer


ANALYTICS_CHART_USER_PROMPTS = {
    1: (
        "Generate **Chart A** for the Analytics page. Follow the system instructions exactly "
        "(### title + single Mermaid block, nothing after)."
    ),
    2: (
        "Generate **Chart B** for the Analytics page. Follow the system instructions exactly "
        "(### title + single Mermaid block, nothing after). It must differ in chart type and topic from a category pie."
    ),
    3: (
        "Generate **Panel C** for the Analytics page: narrative on spend increases, bullet tips to minimize expenses, "
        "then exactly one Mermaid chart showing where costs rose — follow the system instructions."
    ),
    4: (
        "Generate **Panel D** for the Analytics page: income-only narrative (trends, changes), bullet ideas to grow or "
        "stabilize income, then exactly one Mermaid chart built only from income data — follow the system instructions."
    ),
}


def _history_dicts_to_contents(history_dicts):
    contents = []
    for turn in history_dicts:
        role = turn.get("role")
        parts = turn.get("parts") or []
        if role not in ("user", "model") or not parts:
            continue
        text = parts[0].get("text")
        if text is None:
            continue
        contents.append(
            types.Content(
                role=role,
                parts=[types.Part.from_text(text=text)],
            )
        )
    return contents


@login_required
def stream_chat(request):
    analytics_slot_raw = request.GET.get("analytics_chart")
    if analytics_slot_raw in ("1", "2", "3", "4"):
        slot = int(analytics_slot_raw)
        system_instruction = _build_analytics_chart_system_instruction(request, slot)
        user_message = ANALYTICS_CHART_USER_PROMPTS[slot]

        def analytics_event_stream():
            contents = [
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=user_message)],
                )
            ]
            assistant_text = ""
            buffer = ""
            try:
                stream = client.models.generate_content_stream(
                    model="gemini-3-flash-preview",
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.62 if slot in (3, 4) else 0.55,
                    ),
                )
                for chunk in stream:
                    piece = getattr(chunk, "text", None) or ""
                    if not piece:
                        continue
                    assistant_text += piece
                    buffer += piece
                    if len(buffer) > 24 or buffer.endswith(("\n", ".", "!", "?", "`")):
                        yield f"data: {json.dumps({'text': buffer})}\n\n"
                        buffer = ""
                if buffer:
                    yield f"data: {json.dumps({'text': buffer})}\n\n"
            except Exception as exc:
                err = f"\n\n**Something went wrong.** (`{type(exc).__name__}`: {exc})"
                assistant_text += err
                yield f"data: {json.dumps({'text': err})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"

        resp = StreamingHttpResponse(analytics_event_stream(), content_type="text/event-stream")
        resp["Cache-Control"] = "no-cache"
        resp["X-Accel-Buffering"] = "no"
        return resp

    insight_mode = request.GET.get("insight") in ("1", "true", "yes")
    raw_message = (request.GET.get("message") or "").strip()

    if insight_mode:
        user_message = raw_message or DEFAULT_DASHBOARD_INSIGHT_MESSAGE
    else:
        user_message = raw_message
        if not user_message:
            def empty_stream():
                yield f"data: {json.dumps({'text': 'Please enter a message.'})}\n\n"
                yield f"data: {json.dumps({'done': True})}\n\n"

            resp = StreamingHttpResponse(empty_stream(), content_type="text/event-stream")
            resp["Cache-Control"] = "no-cache"
            resp["X-Accel-Buffering"] = "no"
            return resp

    system_instruction = _build_chat_system_instruction(request, insight_mode=insight_mode)

    def event_stream():
        if insight_mode:
            contents = [
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=user_message)],
                )
            ]
        else:
            history = get_history(request)
            history.append({"role": "user", "parts": [{"text": user_message}]})
            request.session["chat_history"] = history
            request.session.save()
            contents = _history_dicts_to_contents(history)

        assistant_text = ""
        buffer = ""

        try:
            stream = client.models.generate_content_stream(
                model="gemini-3-flash-preview",
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.7,
                ),
            )
            for chunk in stream:
                piece = getattr(chunk, "text", None) or ""
                if not piece:
                    continue
                assistant_text += piece
                buffer += piece
                if len(buffer) > 24 or buffer.endswith(("\n", ".", "!", "?", "`")):
                    yield f"data: {json.dumps({'text': buffer})}\n\n"
                    buffer = ""
            if buffer:
                yield f"data: {json.dumps({'text': buffer})}\n\n"
        except Exception as exc:
            err = f"\n\n**Something went wrong.** (`{type(exc).__name__}`: {exc})"
            assistant_text += err
            yield f"data: {json.dumps({'text': err})}\n\n"

        if not insight_mode:
            history = get_history(request)
            history.append({"role": "model", "parts": [{"text": assistant_text}]})
            request.session["chat_history"] = history
            request.session.save()

        yield f"data: {json.dumps({'done': True})}\n\n"

    resp = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    resp["Cache-Control"] = "no-cache"
    resp["X-Accel-Buffering"] = "no"
    return resp

@login_required
def add_account(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    try:
        data = json.loads(request.body)

        title = data.get("title", "").strip()
        description = data.get("description", "").strip()
        balance = data.get("balance")

        if not title or balance is None:
            return JsonResponse({"error": "Invalid input"}, status=400)
        balance = float(balance)

        Account.objects.create(user=request.user, title=title, description=description, balance=balance)

        return HttpResponse(status=200)

    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)


@login_required
def delete_account(request, account_id):
    if request.method not in {"POST", "GET"}:
        return JsonResponse({"error": "POST required"}, status=405)

    account = get_object_or_404(Account, pk=account_id, user=request.user)
    account.delete()
    return redirect("dashboard")


@login_required
def process_receipt_image(request):
   
    uploaded_file = None
    is_Image = False
    
    account_id = ''
    if 'account' in request.POST:
       account_id = request.POST['account']
    
    if 'image' in request.FILES:
        uploaded_file = request.FILES['image']
        is_Image = True
    else:
        uploaded_file = request.FILES['video']
     
    curr_user = request.user   
    context = {}
   
    now = datetime.now()
    now_string = now.strftime("%y%m%d%H%M")
    new_receipt = ReceiptTransaction.objects.create(title=now_string, user=curr_user)
    new_receipt.file.save(uploaded_file.name, uploaded_file, save=True)
    new_receipt_id = str(new_receipt.pk)

    user_id = str(request.user.pk)
    if account_id:
        receipt_image_background_process.delay(new_receipt_id, is_Image, user_id, account_id)
    else:
        receipt_image_background_process.delay(new_receipt_id, is_Image, user_id)
    # ~ image_bytes = None
    # ~ with open(new_receipt.file.path, "rb") as f:
        # ~ image_bytes = f.read()
    
    # ~ existing_categories = Category.objects.all().values('title')
    # ~ categories_string = json.dumps(list(existing_categories), indent=2, cls=DjangoJSONEncoder)
    
    # ~ existing_subcategories = Category.objects.filter(parent__isnull=False).values('title')
    # ~ subcategories_string = json.dumps(list(existing_subcategories), indent=2, cls=DjangoJSONEncoder)

    # ~ prompt_text = (
        # ~ "Extract date, merchant, name, cost, quantity and pick a category from "
       # ~ + categories_string
       # ~ + " and pick an existing super specific subcategory from "
       # ~ + subcategories_string
       # ~ + "if it fits to any of them, otherwise create a new one."
       # ~ + "A subcategory has to be very specific like type of bread or drink."
       # ~ + " It should be an array of jsons for each item with string keys, items translated to english, named lower case."
       # ~ + "Convert money to euro, divide each item. The date is at the bottom of the receipt."
       # ~ + "Under date shoud be stored in a %Y-%m-%d format for strptime, the fields should be empty if no information present"
    # ~ )

    # ~ prompt_contents = None
    # ~ if is_Image:
        # ~ prompt_contents = [
            # ~ types.Part.from_bytes(
                # ~ data=image_bytes,
                # ~ mime_type="image/jpg"
            # ~ ),
            # ~ prompt_text
        # ~ ]
    # ~ else:
        # ~ prompt_contents = [
            # ~ types.Part.from_bytes(
                # ~ data=image_bytes,
                # ~ mime_type="video/mp4"
            # ~ ),
            # ~ prompt_text
        # ~ ]
    
    # ~ response = client.models.generate_content(
        # ~ model="gemini-3.1-pro-preview",
        # ~ contents=prompt_contents
    # ~ )
    
    # ~ clean_content = response.text.replace("```json", "").replace("```", "").strip()
    # ~ data = json.loads(clean_content)
    # ~ for item in data:
        # ~ item_dt = datetime.strptime(item['date'], "%Y-%m-%d")
        
        # ~ curr_category = Category.objects.filter(title=item['category'])
        # ~ if curr_category:
            # ~ curr_category = curr_category[0]
        # ~ else:
            # ~ curr_category = Category.objects.create(title=item['category'])
        
        # ~ curr_subcategory = Category.objects.filter(parent=curr_category, title=item['subcategory'])
        # ~ if curr_subcategory:
            # ~ curr_subcategory = curr_subcategory[0]
        # ~ else:
            # ~ curr_subcategory = Category.objects.create(title=item['subcategory'], parent=curr_category)

        # ~ new_item = ItemTransaction.objects.create(user=curr_user,
                                                  # ~ receipt=new_receipt,
                                                  # ~ cost=item['cost'],
                                                  # ~ quantity=item['quantity'],
                                                  # ~ date=item_dt,
                                                  # ~ category=curr_category,
                                                  # ~ merchant=item['merchant'],
                                                  # ~ name=item['name'],
                                                  # ~ subcategory=curr_subcategory
                                                # ~ )
        # ~ cat = new_item.category
        # ~ budgets = Budget.objects.filter(user=curr_user, category__title=cat.title)
        # ~ if budgets:
            # ~ for budget in budgets:
                # ~ budget.balance += Decimal(new_item.cost)
                # ~ budget.save()
        # ~ if cat.parent:
            # ~ cat.parent.budget += Decimal(new_item.cost)
            # ~ cat.parent.save()
    return render(request, 'home.html', {"active_page": "dashboard"})


def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("dashboard")
    else:
        form = UserCreationForm()
    return render(request, "registration/register.html", {"form": form})
    
    # ~ user = models.ForeignKey(User, on_delete=models.CASCADE)
    # ~ receipt = models.ForeignKey(ReceiptTransaction, on_delete=models.CASCADE, null=True, blank=True)
    # ~ budget = models.ForeignKey(Budget, on_delete=models.CASCADE, null=True, blank=True)
    # ~ cost = models.DecimalField(max_digits=10, decimal_places=2)
    # ~ quantity = models.DecimalField(max_digits=10, decimal_places=2)
    # ~ date = models.DateField()
    # ~ category = models.ForeignKey(Category, on_delete=models.CASCADE)
    # ~ merchant = models.CharField(max_length=100, blank=True, null=True)



@login_required
def quick_add_item(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    account_id = request.POST.get("account") or ""
    curr_account = None
    if account_id:
        curr_account = Account.objects.filter(pk=account_id, user=request.user).first()
        if curr_account is None:
            return JsonResponse({"error": "Invalid account"}, status=400)

    item_name = request.POST.get("name") or ""
    item_quantity_raw = request.POST.get("quantity") or ""
    item_cost_raw = request.POST.get("cost") or ""
    item_merchant = request.POST.get("merchant") or ""
    category_title = request.POST.get("category") or ""

    if not item_name or not item_quantity_raw or not item_cost_raw or not category_title:
        return JsonResponse({"error": "Name, quantity, cost, and category are required"}, status=400)

    curr_category = Category.objects.filter(title=category_title).first()
    if curr_category is None:
        return JsonResponse({"error": "Invalid category"}, status=400)

    try:
        curr_cost = Decimal(str(item_cost_raw).strip().replace(",", "."))
        curr_quantity = Decimal(str(item_quantity_raw).strip().replace(",", "."))
    except (InvalidOperation, TypeError, ValueError):
        return JsonResponse({"error": "Invalid cost or quantity"}, status=400)

    if curr_cost <= 0 or curr_quantity <= 0:
        return JsonResponse({"error": "Cost and quantity must be greater than zero"}, status=400)

    new_item = ItemTransaction.objects.create(user=request.user,
                                   cost=curr_cost,
                                   quantity=curr_quantity,
                                   category=curr_category,
                                   merchant=item_merchant or None,
                                   name=item_name,
                                   account=curr_account, 
                                   date=timezone.localdate())

    if curr_account is not None:
        curr_account.balance -= curr_cost
        curr_account.save(update_fields=["balance"])

    cat = new_item.category
    budgets = Budget.objects.filter(user=request.user, category__title=cat.title)
    if budgets:
        for budget in budgets:
            budget.balance += Decimal(new_item.cost)
            budget.save()

    return render(request, 'home.html', {"active_page": "dashboard"})

@login_required
def add_expense(request):
    return render(request, 'add_expense.html', {"active_page": "add_expense"})

@login_required
def submit_expense(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    receipt_merchant = request.POST.get("merchant") or ""
    account_id = request.POST.get("account") or ""
    receipt_account = None
    if account_id:
        receipt_account = Account.objects.filter(pk=account_id, user=request.user).first()
        if receipt_account is None:
            return JsonResponse({"error": "Invalid account"}, status=400)    

    created_items = 0
    receipt_obj = ReceiptTransaction.objects.create(user=request.user,
                                      title="Manually inputted reciept")

    i = 0
    while f"item_name{i}" in request.POST:
        item_name = request.POST.get(f"item_name{i}") or ""
        item_quantity_raw = request.POST.get(f"item_quantity{i}") or ""
        item_cost_raw = request.POST.get(f"item_cost{i}") or ""
        category_title = request.POST.get(f"item_category{i}") or ""

        if not item_name and not item_quantity_raw and not item_cost_raw and not category_title:
            i += 1
            continue

        if not item_name or not item_quantity_raw or not item_cost_raw or not category_title:
            receipt_obj.delete()
            return JsonResponse({"error": f"Item {i + 1} is missing required fields"}, status=400)

        curr_category = Category.objects.filter(title=category_title).first()
        if curr_category is None:
            receipt_obj.delete()
            return JsonResponse({"error": f"Item {i + 1} has an invalid category"}, status=400)

        try:
            curr_cost = Decimal(str(item_cost_raw).strip().replace(",", "."))
            curr_quantity = Decimal(str(item_quantity_raw).strip().replace(",", "."))
        except (InvalidOperation, TypeError, ValueError):
            receipt_obj.delete()
            return JsonResponse({"error": f"Item {i + 1} has invalid cost or quantity"}, status=400)

        if curr_cost <= 0 or curr_quantity <= 0:
            receipt_obj.delete()
            return JsonResponse({"error": f"Item {i + 1} must have positive cost and quantity"}, status=400)

        new_item = ItemTransaction.objects.create(user=request.user,
                                   cost=curr_cost,
                                   quantity=curr_quantity,
                                   category=curr_category,
                                   merchant=receipt_merchant or None,
                                   date=timezone.localdate(),
                                   receipt=receipt_obj,
                                   account=receipt_account,
                                   name=item_name)

        if receipt_account is not None:
            receipt_account.balance -= curr_cost
            receipt_account.save(update_fields=["balance"])

        cat = new_item.category
        budgets = Budget.objects.filter(user=request.user, category__title=cat.title)
        if budgets:
            for budget in budgets:
                budget.balance += Decimal(new_item.cost)
                budget.save()

        created_items += 1
        i += 1

    if created_items == 0:
        receipt_obj.delete()
        return JsonResponse({"error": "At least one complete expense item is required"}, status=400)

    return render(request, 'home.html', {"active_page": "dashboard"})


@login_required
def add_money(request):
    return render(request, 'add_money.html', {"active_page": "add_money"})

@login_required
def submit_money(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    curr_description = request.POST.get("description", "").strip()
    curr_type = request.POST.get("type", "").strip()
    amount_raw = request.POST.get("amount", "").strip()

    if not curr_type or not amount_raw:
        return JsonResponse({"error": "Amount and type are required"}, status=400)

    try:
        curr_amount = Decimal(str(amount_raw).strip().replace(",", "."))
    except (InvalidOperation, TypeError, ValueError):
        return JsonResponse({"error": "Invalid amount"}, status=400)
    if curr_amount <= 0:
        return JsonResponse({"error": "Amount must be greater than zero"}, status=400)

    account_id = request.POST.get("account") or ""
    curr_account = None
    if account_id:
        curr_account = Account.objects.filter(pk=account_id, user=request.user).first()
        if curr_account is None:
            return JsonResponse({"error": "Invalid account"}, status=400)

    IncomeTransaction.objects.create(user=request.user,
                                    type=curr_type,
                                    amount=curr_amount,
                                    description=curr_description or None,
                                    account=curr_account)

    if curr_account is not None:
        curr_account.balance += curr_amount
        curr_account.save(update_fields=["balance"])

    return redirect("dashboard")

    return render(request, 'home.html', {"active_page": "dashboard"})

def get_history(request):
    raw = request.session.get("chat_history", [])
    cleaned = []
    for turn in raw:
        if not isinstance(turn, dict):
            continue
        role = turn.get("role")
        if role not in ("user", "model"):
            continue
        parts = turn.get("parts")
        if not parts or not isinstance(parts, list):
            continue
        text = parts[0].get("text") if isinstance(parts[0], dict) else None
        if not text:
            continue
        cleaned.append({"role": role, "parts": [{"text": text}]})
    return cleaned


def save_history(request, history):
    request.session["chat_history"] = history



@login_required
def export_to_excel(request):
    rows = list(
        ItemTransaction.objects.filter(user=request.user)
        .select_related("category", "budget", "receipt")
        .order_by("-date")
        .values(
            "date",
            "name",
            "merchant",
            "cost",
            "quantity",
            "category__title",
            "receipt_id",
        )
    )

    structured_rows = [
        {
            "date": row["date"].strftime("%Y-%m-%d") if row["date"] else "",
            "name": row["name"],
            "merchant": row["merchant"],
            "cost": row["cost"],
            "quantity": row["quantity"],
            "category": row["category__title"],
            "receipt_id": str(row["receipt_id"]) if row["receipt_id"] else "",
        }
        for row in rows
    ]

    data_frame = pandas.DataFrame(
        structured_rows,
        columns=[
            "date",
            "name",
            "merchant",
            "cost",
            "quantity",
            "category",
            "receipt_id",
        ],
    )

    output = BytesIO()
    data_frame.to_excel(output, index=False)
    output.seek(0)

    response = HttpResponse(
        output.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="transactions.xlsx"'
    return response


@login_required
def export_to_json(request):
    rows = list(
        ItemTransaction.objects.filter(user=request.user)
        .select_related("category", "budget", "receipt")
        .order_by("-date")
        .values(
            "date",
            "name",
            "merchant",
            "cost",
            "quantity",
            "category__title",
            "receipt_id",
        )
    )

    structured_rows = [
        {
            "date": row["date"].strftime("%Y-%m-%d") if row["date"] else "",
            "name": row["name"],
            "merchant": row["merchant"],
            "cost": row["cost"],
            "quantity": row["quantity"],
            "category": row["category__title"],
            "receipt_id": str(row["receipt_id"]) if row["receipt_id"] else "",
        }
        for row in rows
    ]

    data_frame = pandas.DataFrame(
        structured_rows,
        columns=[
            "date",
            "name",
            "merchant",
            "cost",
            "quantity",
            "category",
            "receipt_id",
        ],
    )

    output = BytesIO()
    data_frame.to_json(output, index=False)
    output.seek(0)

    response = HttpResponse(
        output.getvalue(),
        content_type="application/json"
        )
    response["Content-Disposition"] = 'attachment; filename="transactions.json"'
    return response
