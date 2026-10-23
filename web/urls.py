from django.urls import path

from . import views

app_name = "web"

urlpatterns = [
    path("", views.home, name="home"),
    path("stock/", views.stock, name="stock"),
    path("stock/<int:pk>/", views.reference_detail, name="reference-detail"),
    path("historico/", views.history, name="history"),
    path("definicoes/", views.settings, name="settings"),
    path("entradas/", views.planned_feature, {"section": "entry"}, name="entry"),
    path("saidas/", views.planned_feature, {"section": "exit"}, name="exit"),
    path("inventario/", views.planned_feature, {"section": "inventory"}, name="inventory"),
    path("referencias/", views.planned_feature, {"section": "references"}, name="references"),
]
