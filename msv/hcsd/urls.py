from django.contrib.auth import views as auth_views
from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('companies/', views.company_list, name='company_list'),
    path('company_detail/<int:id>/', views.company_detail, name='company_detail'),
    path('add_company/', views.add_company, name='add_company'),
    path('extensions/followup/', views.extension_followup, name='extension_followup'),
    path('enginers/', views.enginer_list, name='enginer_list'),
    path('enginers/add/', views.enginer_add, name='enginer_add'),
    path('enginers/<int:id>/', views.enginer_detail, name='enginer_detail'),
    path('clearances/', views.clearance_list, name='clearance_list'),
    path('permits/', views.permit_types, name='permit_types'),
    path('permits/pest-control/', views.pest_control_permit, name='pest_control_permit'),
    path('permits/vehicle/', views.vehicle_permit, name='vehicle_permit'),
    path('permits/pest-control/<int:id>/', views.pest_control_permit_detail, name='pest_control_permit_detail'),
    path('permits/vehicle/<int:id>/', views.vehicle_permit_detail, name='vehicle_permit_detail'),
    path('permits/pest-control/<int:id>/view/', views.pest_control_permit_view, name='pest_control_permit_view'),
    path('printer/', views.printer, name='printer'),
    path('printer/<int:permit_id>/', views.printer, name='printer_permit'),
    path('pirmet/<int:id>/', views.pest_control_permit_detail, name='pirmet_detail'),
    path('register/', views.register, name='register'),
    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path(
        'password-reset/',
        auth_views.PasswordResetView.as_view(
            template_name='registration/password_reset_form.html',
            email_template_name='registration/password_reset_email.html',
            subject_template_name='registration/password_reset_subject.txt',
        ),
        name='password_reset',
    ),
    path(
        'password-reset/done/',
        auth_views.PasswordResetDoneView.as_view(
            template_name='registration/password_reset_done.html',
        ),
        name='password_reset_done',
    ),
    path(
        'reset/<uidb64>/<token>/',
        auth_views.PasswordResetConfirmView.as_view(
            template_name='registration/password_reset_confirm.html',
        ),
        name='password_reset_confirm',
    ),
    path(
        'reset/done/',
        auth_views.PasswordResetCompleteView.as_view(
            template_name='registration/password_reset_complete.html',
        ),
        name='password_reset_complete',
    ),
]
