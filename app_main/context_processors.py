from .models import Account

def global_settings(request):
    # You can fetch database objects, check permissions, etc.
    return {
        'accounts': Account.objects.filter(user=request.user)
    }