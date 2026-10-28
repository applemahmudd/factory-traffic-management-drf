from django.urls import path
from traffic import views

urlpatterns = [
    path("api/health", views.health),
    path("api/junctions", views.JunctionListCreateView.as_view()),
    path("api/junctions/<str:junction_id>", views.JunctionDetailView.as_view()),
    path("api/junctions/<str:junction_id>/status", views.JunctionStatusView.as_view()),
    path("api/junctions/<str:junction_id>/commands", views.JunctionCommandsView.as_view()),
    path("api/junctions/<str:junction_id>/tick", views.JunctionTickView.as_view()),
    path("api/junctions/<str:junction_id>/history", views.JunctionHistoryView.as_view()),
    path("api/sensor-events", views.SensorEventView.as_view()),
    path("api/controller-events", views.ControllerEventView.as_view()),
    path("api/device-events", views.DeviceEventView.as_view()),
]
