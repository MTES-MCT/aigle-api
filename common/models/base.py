from .timestamped import TimestampedModelMixin
from .uuid import UuidModelMixin
from .deletable import DeletableModelMixin


class BaseModel(TimestampedModelMixin, UuidModelMixin, DeletableModelMixin):
    """
    Base model following Django Styleguide principles.

    Includes:
    - Automatic timestamping (created_at, updated_at)
    - UUID primary key
    - Soft delete functionality
    """

    class Meta:
        abstract = True

    def clean(self):
        """
        Hook for custom model validation.
        Override this method to add business logic validation.

        This is the recommended place for model-level validation
        according to Django Styleguide.
        """
        super().clean()

    def save(self, *args, **kwargs):
        """
        Override save to always call full_clean() before saving.
        This ensures validation is always run.
        """
        self.full_clean()
        super().save(*args, **kwargs)
