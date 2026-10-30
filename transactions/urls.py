from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("api/chart-data/", views.chart_data, name="chart_data"),
    path("api/open-data-chart/<slug:dataset>/", views.open_data_chart, name="open_data_chart"),
    path("data/<slug:dataset>/", views.open_data_page, name="open_data"),
]