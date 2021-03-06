import requests
from django.views.decorators.http import require_POST
from pyquery import PyQuery
from rest_framework.decorators import api_view
from rest_framework.response import Response
import json

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponseForbidden, HttpResponseRedirect, HttpResponseBadRequest, JsonResponse, Http404
from django.shortcuts import render, get_object_or_404
from django.urls import reverse

from test_helpers import check_response
from .utils import parse_cap_decision_date
from .serializers import ContentAnnotationSerializer, CaseSerializer, TextBlockSerializer
from .models import Casebook, Resource, Section, Case, User, CaseCourt


def login_required_response(request):
    if request.user.is_authenticated:
        return HttpResponseForbidden()
    else:
        return redirect_to_login(request.build_absolute_uri())


@api_view(['GET'])
def annotations(request, resource_id, format=None):
    """
        /resources/:resource_id/annotations view.
        Was: app/controllers/content/annotations_controller.rb
    """
    resource = get_object_or_404(Resource.objects.select_related('casebook'), pk=resource_id)

    # check permissions
    if not resource.casebook.viewable_by(request.user):
        return login_required_response(request)

    if request.method == 'GET':
        return Response(ContentAnnotationSerializer(resource.annotations.all(), many=True).data)


def index(request):
    if request.user.is_authenticated:
        return render(request, 'dashboard.html', {'user': request.user})
    else:
        return render(request, 'index.html')


def dashboard(request, user_id):
    """
        Show given user's casebooks.

        TODO: test with editors, not only owners.

        Given:
        >>> casebook, casebook_factory, client, admin_user, user_factory = [getfixture(f) for f in ['casebook', 'casebook_factory', 'client', 'admin_user', 'user_factory']]
        >>> user = casebook.collaborators.first()
        >>> non_collaborating_user = user_factory()
        >>> private_casebook = casebook_factory(contentcollaborator_set__user=user, public=False)
        >>> draft_casebook = casebook_factory(contentcollaborator_set__user=user, public=False, draft_mode_of_published_casebook=True, copy_of=casebook)
        >>> url = reverse('dashboard', args=[user.id])

        All users can see public casebooks:
        >>> check_response(client.get(url), content_includes=casebook.title)

        Other users cannot see non-public casebooks:
        >>> check_response(client.get(url), content_excludes=private_casebook.title)
        >>> check_response(client.get(url, as_user=non_collaborating_user), content_excludes=private_casebook.title)

        Users can see their own non-public casebooks:
        >>> check_response(client.get(url, as_user=user), content_includes=private_casebook.title)

        Admins can see a user's non-public casebooks:
        >>> check_response(client.get(url, as_user=admin_user), content_includes=private_casebook.title)

        Drafts of published books aren't listed:
        >>> check_response(client.get(url), content_excludes=draft_casebook.title)
        >>> check_response(client.get(url, as_user=user), content_excludes=draft_casebook.title)
        >>> check_response(client.get(url, as_user=admin_user), content_excludes=draft_casebook.title)

        Drafts of published books are described as "unpublished changes" to owners and admins:
        >>> check_response(client.get(url, as_user=user), content_includes="This casebook has unpublished changes.")
        >>> check_response(client.get(url, as_user=admin_user), content_includes="This casebook has unpublished changes.")

        Drafts of published books are not apparent to other users:
        >>> check_response(client.get(url), content_excludes="This casebook has unpublished changes.")
        >>> check_response(client.get(url, as_user=non_collaborating_user), content_excludes="This casebook has unpublished changes.")
    """
    user = get_object_or_404(User, pk=user_id)
    return render(request, 'dashboard.html', {'user': user})


def casebook(request, casebook_param):
    """
        Show a casebook's front page.

        TODO: test with editors, not only owners.
        TODO: build, then test, action buttons :-)

        Given:
        >>> casebook, casebook_factory, client, admin_user, user_factory = [getfixture(f) for f in ['casebook', 'casebook_factory', 'client', 'admin_user', 'user_factory']]
        >>> user = casebook.collaborators.first()
        >>> non_collaborating_user = user_factory()
        >>> private_casebook = casebook_factory(contentcollaborator_set__user=user, public=False)
        >>> draft_casebook = casebook_factory(contentcollaborator_set__user=user, public=False, draft_mode_of_published_casebook=True, copy_of=casebook)

        All users can see public casebooks:
        >>> check_response(client.get(casebook.get_absolute_url(), content_includes=casebook.title))

        Other users cannot see non-public casebooks:
        >>> check_response(client.get(private_casebook.get_absolute_url()), status_code=302)
        >>> check_response(client.get(private_casebook.get_absolute_url(), as_user=non_collaborating_user), status_code=403)

        Users can see their own non-public casebooks in preview mode:
        >>> check_response(
        ...     client.get(private_casebook.get_absolute_url(), as_user=user),
        ...     content_includes=[
        ...         private_casebook.title,
        ...         "You are viewing a preview"
        ...     ]
        ... )

        Admins can see a user's non-public casebooks in preview mode:
        >>> check_response(
        ...     client.get(private_casebook.get_absolute_url(), as_user=user),
        ...     content_includes=[
        ...         private_casebook.title,
        ...         "You are viewing a preview"
        ...     ]
        ... )

        Owners and admins see the "preview mode" of draft casebooks:
        >>> check_response(client.get(draft_casebook.get_absolute_url(), as_user=user), content_includes="You are viewing a preview")
        >>> check_response(client.get(draft_casebook.get_absolute_url(), as_user=admin_user), content_includes="You are viewing a preview")

        Other users cannot see draft casebooks:
        >>> check_response(client.get(draft_casebook.get_absolute_url()), status_code=302)
        >>> check_response(client.get(draft_casebook.get_absolute_url(), as_user=non_collaborating_user), status_code=403)
    """

    casebook = get_object_or_404(Casebook, id=casebook_param['id'])

    # check permissions
    if not casebook.viewable_by(request.user):
        return login_required_response(request)

    # canonical redirect
    canonical = casebook.get_absolute_url()
    if request.path != canonical:
        return HttpResponseRedirect(canonical)

    contents = casebook.contents.prefetch_resources().order_by('ordinals')

    return render(request, 'casebook.html', {
        'casebook': casebook,
        'contents': contents
    })


@login_required
@require_POST
def clone_casebook(request, casebook_param):
    """
        Clone a casebook and redirect to edit page for clone.

        Given:
        >>> casebook, client, user = [getfixture(f) for f in ['casebook', 'client', 'user']]

        Redirect to new clone:
        >>> check_response(client.post(reverse('clone', args=[casebook.pk]), as_user=user), status_code=302)
    """
    casebook = get_object_or_404(Casebook, id=casebook_param['id'])
    clone = casebook.clone(request.user)
    return HttpResponseRedirect(reverse('layout', args=[clone.pk]))


@login_required
@require_POST
def create_draft(request, casebook_param):
    """
        Clone a casebook and redirect to edit page for clone.

        Given:
        >>> casebook, client, user = [getfixture(f) for f in ['casebook', 'client', 'user']]

        Redirect to new draft:
        >>> check_response(client.post(reverse('create_draft', args=[casebook.pk]), as_user=user), status_code=302)
    """
    # TODO: I think this should be checking that user is a collaborator on the casebook, and that no draft exists.
    # I don't immediately see that logic in Rails, though.
    casebook = get_object_or_404(Casebook, id=casebook_param['id'])
    clone = casebook.make_draft()
    return HttpResponseRedirect(reverse('layout', args=[clone.pk]))


def section(request, casebook_param, ordinals_param):
    section = get_object_or_404(Section.objects.select_related('casebook'), casebook=casebook_param['id'], ordinals=ordinals_param['ordinals'])

    # check permissions
    if not section.casebook.viewable_by(request.user):
        return login_required_response(request)

    # canonical redirect
    canonical = section.get_absolute_url()
    if request.path != canonical:
        return HttpResponseRedirect(canonical)

    return render(request, 'section.html', {
        'section': section
    })


def resource(request, casebook_param, ordinals_param):
    resource = get_object_or_404(Resource.objects.select_related('casebook'), casebook=casebook_param['id'], ordinals=ordinals_param['ordinals'])

    # check permissions
    if not resource.casebook.viewable_by(request.user):
        return login_required_response(request)

    # canonical redirect
    canonical = resource.get_absolute_url()
    if request.path != canonical:
        return HttpResponseRedirect(canonical)

    if resource.resource_type == 'Case':
        resource.json = json.dumps(CaseSerializer(resource.resource).data)
    elif resource.resource_type == 'TextBlock':
        resource.json = json.dumps(TextBlockSerializer(resource.resource).data)

    return render(request, 'resource.html', {
        'resource': resource,
        'include_vuejs': resource.resource_type in ['Case', 'TextBlock']
    })


def case(request, case_id):
    case = get_object_or_404(Case, id=case_id)
    if not case.public:
        return HttpResponseForbidden()

    case.json = json.dumps(CaseSerializer(case).data)
    return render(request, 'case.html', {
        'case': case,
        'include_vuejs': True
    })


@login_required
def from_capapi(request):
    """
        Given a posted CAP ID, return the internal ID for the same case, first ingesting the case from CAP if necessary.

        Given:
        >>> capapi_mock, client, user, case_factory = [getfixture(i) for i in ['capapi_mock', 'client', 'user', 'case_factory']]
        >>> url = reverse('from_capapi')
        >>> existing_case = case_factory(capapi_id=9999)

        Existing cases will be returned without hitting the CAP API:
        >>> response = client.post(url, json.dumps({'id': 9999}), content_type="application/json", as_user=user)
        >>> check_response(response, content_includes='{"id": %s}' % existing_case.id, content_type='application/json')

        Non-existing cases will be fetched and created:
        >>> response = client.post(url, json.dumps({'id': 12345}), content_type="application/json", as_user=user)
        >>> check_response(response, content_type='application/json')
        >>> case = Case.objects.get(id=json.loads(response.content.decode())['id'])
        >>> assert case.name_abbreviation == "1-800 Contacts, Inc. v. Lens.Com, Inc."
        >>> assert case.opinions == {"majority": "HARTZ, Circuit Judge."}
    """
    # parse ID from request:
    try:
        data = json.loads(request.body.decode("utf-8"))
        cap_id = int(data['id'])
    except Exception:
        raise HttpResponseBadRequest

    # try to fetch existing case:
    case = Case.objects.filter(capapi_id=cap_id, public=True).first()

    if not case:
        # fetch from CAP:
        response = requests.get(
            settings.CAPAPI_BASE_URL+"cases/%s/" % cap_id,
            {"full_case": "true", "body_format": "html"},
            headers={'Authorization': 'Token %s' % settings.CAPAPI_API_KEY},
        )
        cap_case = response.json()

        # get or create local CaseCourt object:
        # (don't use get_or_create() because current data may have duplicates; we get the first one by id)
        court_args = {
            "capapi_id": cap_case['court']['id'],
            "name": cap_case['court']['name'],
            "name_abbreviation": cap_case['court']['name_abbreviation'],
        }
        court = CaseCourt.objects.filter(**court_args).order_by('id').first()
        if not court:
            court = CaseCourt(**court_args)
            court.save()

        # parse html:
        parsed = PyQuery(cap_case['casebody']['data'])

        # create case:
        case = Case(
            # our db metadata
            created_via_import=True,
            public=True,
            capapi_id=cap_id,

            # cap case metadata
            case_court=court,
            name_abbreviation=cap_case['name_abbreviation'],
            name=cap_case['name'],
            docket_number=cap_case['docket_number'],
            citations=cap_case['citations'],
            decision_date=parse_cap_decision_date(cap_case['decision_date']),

            # cap case html
            content=cap_case['casebody']['data'],
            attorneys=[el.text() for el in parsed('.attorneys').items()],
            # TODO: copying a Rails bug. Using a dict here is incorrect, as the same data-type can appear more than once:
            opinions={el.attr('data-type'): el('.author').text() for el in parsed('.opinion').items()},
        )
        case.save()

    return JsonResponse({'id': case.id})


def not_implemented_yet(request):
    """ Used for routes we want to be able to reverse(), but that aren't implemented yet. """
    raise Http404
