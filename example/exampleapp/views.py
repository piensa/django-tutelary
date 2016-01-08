import django.views.generic as generic
import django.views.generic.edit as edit
from django.core.urlresolvers import reverse, reverse_lazy
from .models import Party, Parcel
from django.contrib.auth.models import User
from tutelary.models import Policy


class UserMixin:
    def get_context_data(self, **kwargs):
        context = super(UserMixin, self).get_context_data(**kwargs)
        context['users'] = User.objects.all()
        return context


class ListView(UserMixin, generic.ListView):
    pass


class DetailView(UserMixin, generic.DetailView):
    pass


class CreateView(UserMixin, edit.CreateView):
    pass


class UpdateView(UserMixin, edit.UpdateView):
    pass


class DeleteView(UserMixin, edit.DeleteView):
    pass


class IndexView(UserMixin, generic.TemplateView):
    template_name = 'exampleapp/index.html'


class UserList(ListView):
    model = User


class UserDetail(DetailView):
    model = User


class UserCreate(CreateView):
    model = User
    fields = ['username', 'email']

    def get_success_url(self):
        return reverse('user-detail', kwargs={'pk': self.object.pk})


class UserUpdate(UpdateView):
    model = User
    fields = ['username', 'email']
    template_name_suffix = '_update_form'

    def get_success_url(self):
        return reverse('user-detail', kwargs={'pk': self.object.pk})


class UserDelete(DeleteView):
    model = User
    success_url = reverse_lazy('user-list')


class PolicyList(ListView):
    model = Policy


class PolicyDetail(DetailView):
    model = Policy


class PolicyCreate(CreateView):
    model = Policy
    fields = ['name', 'body']

    def get_success_url(self):
        return reverse('policy-detail', kwargs={'pk': self.object.pk})


class PolicyUpdate(UpdateView):
    model = Policy
    fields = ['name', 'body']
    template_name_suffix = '_update_form'

    def get_success_url(self):
        return reverse('policy-detail', kwargs={'pk': self.object.pk})


class PolicyDelete(DeleteView):
    model = Policy
    success_url = reverse_lazy('policy-list')


class PartyList(ListView):
    model = Party


class PartyDetail(DetailView):
    model = Party


class PartyCreate(CreateView):
    model = Party
    fields = ['name', 'address', 'status']


class PartyUpdate(UpdateView):
    model = Party
    fields = ['name', 'address', 'status']
    template_name_suffix = '_update_form'


class PartyDelete(DeleteView):
    model = Party
    success_url = reverse_lazy('party-list')


class ParcelList(ListView):
    model = Parcel


class ParcelDetail(DetailView):
    model = Parcel


class ParcelCreate(CreateView):
    model = Parcel
    fields = ['address', 'status']


class ParcelUpdate(UpdateView):
    model = Parcel
    fields = ['address', 'status']
    template_name_suffix = '_update_form'


class ParcelDelete(DeleteView):
    model = Parcel
    success_url = reverse_lazy('parcel-list')