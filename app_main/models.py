from django.contrib.auth.models import User
from django.db import models

# Create your models here.
class Budget(models.Model):
    title = models.CharField(max_length=100)
    balance = models.DecimalField(max_digits=10, decimal_places=2)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    limit = models.DecimalField(max_digits=10, decimal_places=2)

class ReceiptTransaction(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    file = models.FileField(upload_to='receipts/', blank=True, null=True)
    title = models.CharField(max_length=100, blank=True, null=True)

class Category(models.Model):
    title = models.CharField(max_length=100)
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True)

class ItemTransaction(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    receipt = models.ForeignKey(ReceiptTransaction, on_delete=models.CASCADE, null=True, blank=True)
    budget = models.ForeignKey(Budget, on_delete=models.CASCADE, null=True, blank=True)
    cost = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateField(auto_now=True)
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    merchant = models.CharField(max_length=100, blank=True, null=True)
    name = models.CharField(max_length=100, blank=True, null=True)

class ScheduleExpense(models.Model):
    title = models.CharField(max_length=100)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    cost = models.DecimalField(max_digits=10, decimal_places=2)
    type = models.CharField(max_length=100) #week,month,year
    dayofweek = models.IntegerField()

class Account(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    title = models.CharField(max_length=100)
    description = models.CharField(max_length=255)
    balance = models.DecimalField(max_digits=20, decimal_places=2)

class IncomeTransaction(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    description = models.CharField(max_length=255)
    date = models.DateField(auto_now=True)
    type = models.CharField(max_length=100)