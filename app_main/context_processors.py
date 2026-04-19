from .models import Account, ItemTransaction

def global_settings(request):
    if request.user.is_authenticated:
        accounts = Account.objects.filter(user=request.user)
        num_flagged = ItemTransaction.objects.filter(user=request.user, account__isnull=True).count()
    else:
        accounts = Account.objects.none()

    return {
        "accounts": accounts,
        "num_flagged": num_flagged
    }
