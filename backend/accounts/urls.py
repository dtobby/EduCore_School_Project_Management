from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView

from .views import ActiveUserTokenRefreshView, MeView

urlpatterns = [
    path("token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("token/refresh/", ActiveUserTokenRefreshView.as_view(), name="token_refresh"),
    path("me/", MeView.as_view(), name="me"),
]
