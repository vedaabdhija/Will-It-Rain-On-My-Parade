from django.urls import path
from . import views

# This file maps the URL path to the view function.
urlpatterns = [
    # When a request comes to /predict, call the predict_weather view.
    path('predict', views.predict_weather, name='predict_weather'),
]

