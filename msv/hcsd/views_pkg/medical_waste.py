"""
Medical Waste Inspection — standalone system (in development).

URL prefix : /medical-waste/
Templates  : hcsd/medical_waste_*.html
"""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def medical_waste_home(request):
    return render(request, 'hcsd/medical_waste_home.html')
