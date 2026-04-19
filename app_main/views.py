from django.db.models.aggregates import Sum
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect
from datetime import datetime
from bson import ObjectId
from google.genai import types
from google import genai

from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.core.serializers.json import DjangoJSONEncoder
from .models import ReceiptTransaction, Category, ItemTransaction, Account

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
    return render(request, 'recurring.html', {"active_page": "recurring"})


@login_required
def analytics(request):
    return render(request, 'analytics.html', {"active_page": "analytics"})


@login_required
def budgets(request):
    return render(request, 'budgets.html', {"active_page": "budgets"})


@login_required
def chat(request):
    return render(request, 'chat.html', {"active_page": "chat"})


@login_required
def scan_receipt(request):
    return render(request, 'scan_receipt.html', {"active_page": "scan"})

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
    return render(request, 'home.html', {"active_page": "dashboard"})
