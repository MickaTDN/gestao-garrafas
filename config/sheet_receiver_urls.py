from django.urls import path

from consultation.wifi import receive

urlpatterns = [path("v1/pending-sheets", receive)]
