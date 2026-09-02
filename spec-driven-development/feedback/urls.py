from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("identify/", views.identify, name="identify"),
    path("sign-out/", views.sign_out, name="sign_out"),
    path("projects/new/", views.project_create, name="project_create"),
    path("projects/<int:project_id>/", views.project_detail, name="project_detail"),
    path(
        "projects/<int:project_id>/feedback/",
        views.add_feedback,
        name="add_feedback",
    ),
    path(
        "projects/<int:project_id>/members/add/",
        views.add_member,
        name="add_member",
    ),
    path(
        "projects/<int:project_id>/members/<int:member_id>/remove/",
        views.remove_member,
        name="remove_member",
    ),
]
