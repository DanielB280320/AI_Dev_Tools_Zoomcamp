from django.urls import include, path

urlpatterns = [
    path("", include("feedback.urls")),
]
