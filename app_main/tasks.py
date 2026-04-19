from decimal import Decimal

from DH26 import celery_app
from datetime import datetime
from google.genai import types
from google import genai
import json

from django.contrib.auth import login
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.core.serializers.json import DjangoJSONEncoder
from .models import ReceiptTransaction, Category, ItemTransaction, Budget

from DH26 import settings


client = genai.Client(api_key=settings.GEMINI_API_KEY)


@celery_app.task(name="process_receipt_image")
def receipt_image_background_process(receipt_id,  is_Image, user_id):
    new_receipt = ReceiptTransaction.objects.get(id=receipt_id)
    curr_user = User.objects.get(id=user_id)
    
    image_bytes = None
    with open(new_receipt.file.path, "rb") as f:
        image_bytes = f.read()
    
    existing_categories = Category.objects.all().values('title')
    categories_string = json.dumps(list(existing_categories), indent=2, cls=DjangoJSONEncoder)
    
    existing_subcategories = Category.objects.filter(parent__isnull=False).values('title')
    subcategories_string = json.dumps(list(existing_subcategories), indent=2, cls=DjangoJSONEncoder)
    
    prompt_text = (
        "Extract date, merchant, name, cost, quantity and pick a category from "
       + categories_string
       + " and pick an existing super specific subcategory from "
       + subcategories_string
       + "if it fits to any of them, otherwise create a new one."
       + "A subcategory has to be very specific like type of bread or drink."
       + " It should be an array of jsons for each item with string keys, items translated to english, named lower case." 
       + "Convert money to euro, divide each item. The date is at the bottom of the receipt."
       + "Under date shoud be stored in a %Y-%m-%d format for strptime, the fields should be empty if no information present"
    )
    
    prompt_contents = None
    if is_Image:
        prompt_contents = [
            types.Part.from_bytes(
                data=image_bytes,
                mime_type="image/jpg"
            ),
            prompt_text
        ]
    else:
        prompt_contents = [
            types.Part.from_bytes(
                data=image_bytes,
                mime_type="video/mp4"
            ),
            prompt_text
        ]
    
    response = client.models.generate_content(
        model="gemini-3.1-pro-preview",
        contents=prompt_contents
    )
    
    clean_content = response.text.replace("```json", "").replace("```", "").strip()
    data = json.loads(clean_content)
    for item in data:
        item_dt = datetime.strptime(item['date'], "%Y-%m-%d")
        
        curr_category = Category.objects.filter(title=item['category'])
        if curr_category:
            curr_category = curr_category[0]
        else:
            curr_category = Category.objects.create(title=item['category'])
        
        curr_subcategory = Category.objects.filter(parent=curr_category, title=item['subcategory'])
        if curr_subcategory:
            curr_subcategory = curr_subcategory[0]
        else:
            curr_subcategory = Category.objects.create(title=item['subcategory'], parent=curr_category)
        
        new_item = ItemTransaction.objects.create(user=curr_user,
                                                  receipt=new_receipt,
                                                  cost=item['cost'],
                                                  quantity=item['quantity'],
                                                  date=item_dt,
                                                  category=curr_category,
                                                  merchant=item['merchant'],
                                                  name=item['name'],
                                                  subcategory=curr_subcategory
                                                )
        cat = new_item.category
        budgets = Budget.objects.filter(user=curr_user, category__title=cat.title)
        if budgets:
            for budget in budgets:
                budget.balance += Decimal(new_item.cost)
                budget.save()
        if cat.parent:
            cat.parent.budget += Decimal(new_item.cost)
            cat.parent.save()