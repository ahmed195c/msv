from django.conf import settings
from django.contrib import admin
from django.contrib.staticfiles import views as staticfiles_views
from django.urls import path, include, re_path
from django.views.static import serve as media_serve

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('hcsd.urls')),
    # insecure=True bypasses the DEBUG check; nginx intercepts these in production
    re_path(r'^static/(?P<path>.*)$', staticfiles_views.serve, {'insecure': True}),
    re_path(r'^media/(?P<path>.*)$', media_serve, {'document_root': settings.MEDIA_ROOT}),
]
