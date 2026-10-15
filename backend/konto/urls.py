from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import EinrichtungView, LoginView, LogoutView

urlpatterns = [
    path("login/", LoginView.as_view(), name="konto-login"),
    path("jwt/refresh/", TokenRefreshView.as_view(), name="konto-refresh"),
    path("logout/", LogoutView.as_view(), name="konto-logout"),
    path("einrichtung/", EinrichtungView.as_view(), name="konto-einrichtung"),
]
