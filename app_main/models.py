from django.contrib.auth.models import User
from django.utils import timezone
from django.db import models

class Account(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    title = models.CharField(max_length=100)
    description = models.CharField(max_length=255)
    balance = models.DecimalField(max_digits=20, decimal_places=2)

class Category(models.Model):
    title = models.CharField(max_length=100)
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True)

class Budget(models.Model):
    title = models.CharField(max_length=100)
    balance = models.DecimalField(max_digits=10, decimal_places=2)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    limit = models.DecimalField(max_digits=10, decimal_places=2)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, null=True)

    @property
    def percentage(self):
        if self.limit == 0:
            return 0
        calc = (self.balance / self.limit) * 100
        return round(calc, 2)

    @property
    def remaining(self):
        return self.limit - self.balance

class ReceiptTransaction(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    file = models.FileField(upload_to='receipts/', blank=True, null=True)
    title = models.CharField(max_length=100, blank=True, null=True)
    account = models.ForeignKey(Account, on_delete=models.CASCADE, null=True)


class ItemTransaction(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    receipt = models.ForeignKey(ReceiptTransaction, on_delete=models.CASCADE, null=True, blank=True)
    budget = models.ForeignKey(Budget, on_delete=models.CASCADE, null=True, blank=True)
    cost = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateField()
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    merchant = models.CharField(max_length=100, blank=True, null=True)
    name = models.CharField(max_length=100, blank=True, null=True)
    subcategory = models.ForeignKey(Category, on_delete=models.CASCADE, null=True, related_name="subcategory")
    account = models.ForeignKey(Account, on_delete=models.CASCADE, null=True)

class ScheduleExpense(models.Model):

    TYPE_OF_EXPENSE = (
        ("DAILY", "Daily"),
        ("WEEKLY", "Weekly"),
        ("MONTHLY", "Monthly"),
        ("YEARLY", "Yearly")
    )

    title = models.CharField(max_length=100)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    cost = models.DecimalField(max_digits=10, decimal_places=2)
    account = models.ForeignKey(Account, on_delete=models.CASCADE, null=True)
    type = models.CharField(max_length=10, choices=TYPE_OF_EXPENSE)


class IncomeTransaction(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    description = models.CharField(max_length=255, blank=True, null=True)
    date = models.DateField(auto_now=True)
    type = models.CharField(max_length=100)
    account = models.ForeignKey(Account, on_delete=models.CASCADE, blank=True, null=True)
