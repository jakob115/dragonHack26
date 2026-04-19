from decimal import Decimal, InvalidOperation

from django.db.models.aggregates import Sum
from django.http import JsonResponse, HttpResponse, StreamingHttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from datetime import datetime
from bson import ObjectId
from google.genai import types
from google import genai

from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.core.serializers.json import DjangoJSONEncoder
from .models import ReceiptTransaction, Category, ItemTransaction, Account, IncomeTransaction, ScheduleExpense

from .tasks import receipt_image_background_process

from DH26 import settings

import json

client = genai.Client(api_key=settings.GEMINI_API_KEY)

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
    context['recurring_expenses'] = ScheduleExpense.objects.filter(user=request.user)
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
    recurring_title = (request.POST.get("title") or "").strip()
    recurring_cost = request.POST.get("cost")
    recurring_type = request.POST.get("type")
    recurring_account_id = request.POST.get("account")
    recurring_account = None
    valid_types = {choice[0] for choice in ScheduleExpense.TYPE_OF_EXPENSE}

    if not recurring_title or not recurring_cost or recurring_type not in valid_types:
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
def analytics(request):
    return render(request, 'analytics.html', {"active_page": "analytics"})


@login_required
def budgets(request):
    return render(request, 'budgets.html', {"active_page": "budgets"})


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


def _build_chat_system_instruction(request):
    tx_json = _chat_transactions_payload(request)
    tx_blob = json.dumps(tx_json, indent=2, cls=DjangoJSONEncoder)

    # Do not use an f-string for the whole prompt: JSON may contain "{" / "}" and break parsing.
    return (
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
    user_message = (request.GET.get("message") or "").strip()
    if not user_message:
        def empty_stream():
            yield f"data: {json.dumps({'text': 'Please enter a message.'})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"

        resp = StreamingHttpResponse(empty_stream(), content_type="text/event-stream")
        resp["Cache-Control"] = "no-cache"
        resp["X-Accel-Buffering"] = "no"
        return resp

    system_instruction = _build_chat_system_instruction(request)

    def event_stream():
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
def process_receipt_image(request):
    uploaded_file = None
    is_Image = False

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
    
    receipt_image_background_process.delay(new_receipt_id, is_Image, user_id)
    # ~ image_bytes = None
    # ~ with open(new_receipt.file.path, "rb") as f:
        # ~ image_bytes = f.read()
    
    # ~ existing_categories = Category.objects.all().values('title')
    # ~ categories_string = json.dumps(list(existing_categories), indent=2, cls=DjangoJSONEncoder)
    
    # ~ prompt_text = (
        # ~ "Extract date, merchant, name, cost, quantity and pick a category from "
       # ~ + categories_string
       # ~ + "if it fits to any of them, otherwise create a new one."
       # ~ + " in json format in english in this order, named lower case."
       # ~ + "Add a field 'existing category'"
       # ~ + "and put True if you picked from list and False if you made a new one."
       # ~ + "Convert money to euro, divide each item."
       # ~ + "The date shoud be in a %Y-%m-%d format, the fields should be empty if no information present"
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
        # ~ model="gemini-3-flash-preview",
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
        
        # ~ new_item = ItemTransaction.objects.create(user=curr_user,
                                                  # ~ receipt=new_receipt,
                                                  # ~ cost=item['cost'],
                                                  # ~ quantity=item['quantity'],
                                                  # ~ date=item_dt,
                                                  # ~ category=curr_category,
                                                  # ~ merchant=item['merchant'],
                                                  # ~ name=item['name']
                                                # ~ )
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

    curr_category = request.POST.get("category")
    curr_category = Category.objects.get(title=curr_category)

    ItemTransaction.objects.create(user=request.user,
                                   cost=request.POST.get("cost"),
                                   quantity=request.POST.get("quantity"),
                                   category=curr_category,
                                   merchant=request.POST.get("merchant"),
                                   name=request.POST.get("name"))
    return render(request, 'home.html', {"active_page": "dashboard"})

@login_required
def add_expense(request):
    return render(request, 'add_expense.html', {"active_page": "add_expense"})

@login_required
def submit_expense(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    receipt_merchant = request.POST.get("merchant")
    
    receipt_obj = ReceiptTransaction.objects.create(user=request.user,
                                      title="Manually inputted reciept")

    i = 0
    while f"item_name{i}" in request.POST:
        curr_category = request.POST.get(f"item_category{i}")
        curr_category = Category.objects.get(title=curr_category)

        ItemTransaction.objects.create(user=request.user,
                                   cost=request.POST.get(f"item_cost{i}"),
                                   quantity=request.POST.get(f"item_quantity{i}"),
                                   category=curr_category,
                                   merchant=receipt_merchant,
                                   receipt=receipt_obj,
                                   name=request.POST.get(f"item_name{i}"))
        i += 1


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
        curr_amount = Decimal(amount_raw)
    except (InvalidOperation, TypeError):
        return JsonResponse({"error": "Invalid amount"}, status=400)

    account_id = request.POST.get("account", "")
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
