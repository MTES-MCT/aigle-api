from django.contrib.auth.base_user import BaseUserManager


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("The given email must be set")

        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        from core.models.user import UserRole

        extra_fields.setdefault("user_role", UserRole.REGULAR)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password, **extra_fields):
        from core.models.user import UserRole

        extra_fields.setdefault("user_role", UserRole.SUPER_ADMIN)

        if extra_fields.get("user_role") is not UserRole.SUPER_ADMIN:
            raise ValueError("Superuser must have user_role=SUPER_ADMIN.")

        return self._create_user(email, password, **extra_fields)
