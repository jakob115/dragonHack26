from django.contrib import admin
from .models import *

admin.site.register(Category)
admin.site.register(Account)
admin.site.register(ItemTransaction)
admin.site.register(IncomeTransaction)
admin.site.register(Budget)
