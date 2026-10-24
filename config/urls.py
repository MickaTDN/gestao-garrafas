from django.contrib.auth import views as auth_views
from django.urls import include, path

from accounts.views import ProtectedLoginView
from web import pwa

urlpatterns = [
    path("ligacao/", pwa.connection_status, name="connection-status"),
    path("manifest.webmanifest", pwa.manifest, name="manifest"),
    path("service-worker.js", pwa.service_worker, name="service-worker"),
    path("offline/", pwa.offline, name="offline"),
    path("entrar/", ProtectedLoginView.as_view(), name="login"),
    path("sair/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("web.urls")),
]
