from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import LoginView

urlpatterns = [
    path("login/", LoginView.as_view(), name="konto-login"),
    path("jwt/refresh/", TokenRefreshView.as_view(), name="konto-refresh"),
]
