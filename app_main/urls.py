from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('register/', views.register, name='register'),
    path('', views.home, name="dashboard"),
    path('home/', views.home, name="home"),
    path('transactions/', views.transactions, name="transactions"),
    path('recurring/', views.recurring, name="recurring"),
    path('analytics/', views.analytics, name="analytics"),
    path('chat/', views.chat, name="chat"),
    path('budgets/', views.budgets, name="budgets"),
    path('budgets/add/', views.add_budget, name="add_budget"),
    path('add_account/', views.add_account, name="add_account"),
    path('scan-receipt/', views.process_receipt_image, name="scan_receipt"),
    path('add-item/', views.quick_add_item, name="quick_add_item"),
    path('add-expense/', views.add_expense, name="add_expense"),
    path('submit-expense/', views.submit_expense, name="submit_expense"),
    path('add-money/', views.add_money, name="add_money"),
    path('create-recurring/', views.create_reccuring, name="create-recurring"),

    path('delete-transaction-receipt/<str:receipt_id>', views.delete_transaction_receipt, name="delete-transaction-receipt"),
    path('delete-transaction-item/<str:item_id>', views.delete_transaction_item, name="delete-transaction-item"),
    path('edit-transaction-item/<str:item_id>', views.edit_transaction_item, name="edit-transaction-item"),
    path('edit-item/', views.edit_item, name="edit_item"),
    path('submit-money/', views.submit_money, name="submit_money"),
    path('stream/', views.stream_chat, name="stream")
]

