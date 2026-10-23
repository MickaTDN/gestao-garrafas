from django.contrib.auth import views as auth_views
from django.urls import include, path

urlpatterns = [
    path("entrar/", auth_views.LoginView.as_view(), name="login"),
    path("sair/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("web.urls")),
]
