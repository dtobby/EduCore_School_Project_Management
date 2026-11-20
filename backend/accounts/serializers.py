from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import RefreshToken


User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email", "first_name", "last_name", "role"]
        read_only_fields = fields


class ActiveUserTokenRefreshSerializer(TokenRefreshSerializer):
    """Refresh only works while the user still exists and is active (FR-03)."""

    def validate(self, attrs):
        refresh = RefreshToken(attrs["refresh"])
        user_id = refresh.payload.get(api_settings.USER_ID_CLAIM)
        is_active = User.objects.filter(
            **{api_settings.USER_ID_FIELD: user_id, "is_active": True}
        ).exists()
        if not is_active:
            raise AuthenticationFailed(
                "User is inactive or no longer exists.", code="user_inactive"
            )
        return super().validate(attrs)