from django.urls import path

from consultation import views as consultation_views

from . import catalog, exports, import_views, operations, reports, user_admin, views

app_name = "web"

urlpatterns = [
    path("exportar/vertente-aveludada/", consultation_views.export, name="vertente-export"),
    path("", views.home, name="home"),
    path("stock/", views.stock, name="stock"),
    path("stock/<int:pk>/", views.reference_detail, name="reference-detail"),
    path("historico/", views.history, name="history"),
    path("definicoes/", views.settings, name="settings"),
    path("entradas/", operations.start, {"kind": "entry"}, name="entry"),
    path("saidas/", operations.start, {"kind": "exit"}, name="exit"),
    path("inventario/", operations.start, {"kind": "inventory"}, name="inventory"),
    path("rascunhos/", operations.drafts, name="drafts"),
    path("operacoes/<int:pk>/editar/", operations.edit, name="operation-edit"),
    path("operacoes/<int:pk>/conferir/", operations.review, name="operation-review"),
    path("operacoes/<int:pk>/cancelar/", operations.cancel, name="operation-cancel"),
    path("operacoes/<int:pk>/nova-referencia/", operations.new_reference, name="operation-reference"),
    path("operacoes/<int:pk>/reativar/<int:reference_pk>/", operations.reactivate, name="operation-reactivate"),
    path("operacoes/<int:pk>/corrigir/", operations.correction, name="operation-correction"),
    path("operacoes/<int:pk>/", operations.detail, name="operation-detail"),
    path("utilizadores/", user_admin.accounts, name="users"),
    path("utilizadores/novo/", user_admin.create, name="user-create"),
    path("utilizadores/<int:pk>/editar/", user_admin.edit, name="user-edit"),
    path("exportar/", exports.export, name="export"),
    path("relatorios/", reports.reports, name="reports"),
    path("documentos/<int:pk>/", reports.content, name="document-content"),
    path("referencias/", catalog.reference_list, name="references"),
    path("referencias/nova/", catalog.reference_create, name="reference-create"),
    path("referencias/<int:pk>/editar/", catalog.reference_edit, name="reference-edit"),
    path("referencias/<int:pk>/estado/", catalog.reference_toggle, name="reference-toggle"),
    path("localizacoes/", catalog.location_list, name="locations"),
    path("localizacoes/nova/", catalog.location_create, name="location-create"),
    path("localizacoes/<int:pk>/editar/", catalog.location_edit, name="location-edit"),
    path("localizacoes/<int:pk>/remover/", catalog.location_delete, name="location-delete"),
    path("setores/novo/", catalog.sector_create, name="sector-create"),
    path("setores/<int:pk>/editar/", catalog.sector_edit, name="sector-edit"),
    path("setores/<int:pk>/remover/", catalog.sector_delete, name="sector-delete"),
    path("importacoes/", import_views.import_list, name="import-list"),
    path("importacoes/<uuid:pk>/", import_views.import_preview, name="import-preview"),
    path("importacoes/<uuid:pk>/relatorio/", import_views.import_report, name="import-report"),
    path("importacoes/<uuid:pk>/publicar/", import_views.import_publish, name="import-publish"),
]
