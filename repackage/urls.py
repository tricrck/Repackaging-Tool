from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from projects import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", views.index, name="index"),
    path("projects/", views.project_list, name="project_list"),
    path("projects/new/", views.project_new, name="project_new"),
    path("projects/<int:pk>/", views.project_detail, name="project_detail"),
    path("projects/<int:pk>/start/", views.project_start, name="project_start"),
    path("projects/<int:pk>/status/", views.project_status, name="project_status"),
    path("projects/<int:pk>/download/", views.project_download, name="project_download"),
    path("projects/<int:pk>/delete/", views.project_delete, name="project_delete"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)