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
    path('scan-receipt/', views.scan_receipt, name="scan_receipt"),
    path('scan-receipt/process/', views.process_receipt_image, name="scan_receipt_process"),
    path('add_account/', views.add_account, name="add_account"),
]
