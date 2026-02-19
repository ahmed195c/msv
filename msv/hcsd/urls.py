from django.contrib.auth import views as auth_views
from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('companies/', views.company_list, name='company_list'),
    path('company_detail/<int:id>/', views.company_detail, name='company_detail'),
    path('add_company/', views.add_company, name='add_company'),
    path('enginers/', views.enginer_list, name='enginer_list'),
    path('enginers/<int:id>/', views.enginer_detail, name='enginer_detail'),
    path('clearances/', views.clearance_list, name='clearance_list'),
    path('permits/', views.permit_types, name='permit_types'),
    path('permits/pest-control/', views.pest_control_permit, name='pest_control_permit'),
    path('permits/pest-control/<int:id>/', views.pest_control_permit_detail, name='pest_control_permit_detail'),
    path('permits/pest-control/<int:id>/view/', views.pest_control_permit_view, name='pest_control_permit_view'),
    path('printer/', views.printer, name='printer'),
    path('pirmet/<int:id>/', views.pest_control_permit_detail, name='pirmet_detail'),
    path('register/', views.register, name='register'),
    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
]
