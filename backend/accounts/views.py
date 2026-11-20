from rest_framework import generics
from rest_framework_simplejwt.views import TokenRefreshView

from .serializers import ActiveUserTokenRefreshSerializer, UserSerializer


class ActiveUserTokenRefreshView(TokenRefreshView):
    serializer_class = ActiveUserTokenRefreshSerializer


class MeView(generics.RetrieveAPIView):
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user
