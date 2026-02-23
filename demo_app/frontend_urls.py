from django.urls import path
from . import frontend_views as v

urlpatterns = [
    path("", v.HomeView.as_view(), name="home"),
    path("posts/<str:pk>/", v.PostDetailView.as_view(), name="post-detail"),
    path("posts/<str:pk>/comment/", v.AddCommentView.as_view(), name="add-comment"),
    path("write/", v.WritePostView.as_view(), name="write-post"),
    path("authors/<str:pk>/", v.AuthorDetailView.as_view(), name="author-detail-fe"),
    path("tags/<slug:slug>/", v.TagDetailView.as_view(), name="tag-detail-fe"),
    path("categories/<slug:slug>/", v.CategoryDetailView.as_view(), name="category-detail-fe"),
]
