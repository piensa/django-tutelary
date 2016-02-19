import json
import hashlib
import itertools
from django.db import models
from django.conf import settings
from django.db.models.signals import pre_delete, post_delete
from django.dispatch import receiver
from django.core.exceptions import ObjectDoesNotExist
from audit_log.models.managers import AuditLog
import tutelary.engine as engine


class Policy(models.Model):
    """An individual policy has a name and a JSON policy body.  Changes to
    policies are audited.

    """

    name = models.CharField(max_length=200)

    body = models.TextField()
    """Policy body, possibly including variables."""

    audit_log = AuditLog()

    def __str__(self):
        return self.name


class PolicyInstance(models.Model):
    """An instance of a policy provides fixed values for any variables
    used in the policy's body.  An ordered sequence of policy
    instances defines a permission set.

    """

    policy = models.ForeignKey('Policy', on_delete=models.PROTECT)

    pset = models.ForeignKey('PermissionSet', on_delete=models.CASCADE)

    index = models.IntegerField()
    """Integer index used to order the sequence of policies composing a
    permission set.

    """

    variables = models.TextField()
    """JSON dump of dictionary giving variable assignments for policy
    instance.

    """

    class Meta:
        ordering = ['index']


def policy_psets(policies):
    """Find the IDs of all permission sets making use of all of a list of
    policies.  The input is a list of (policy, variables) pairs.

    """
    if len(policies) == 0:
        # Special case: find any permission sets that don't have
        # associated policy instances.
        pipsets = set([pi.pset.id for pi in PolicyInstance.objects.all()])
        allpsets = set([pset.id for pset in PermissionSet.objects.all()])
        return list(allpsets - pipsets)
    else:
        psetids = None
        for p in policies:
            pis = PolicyInstance.objects.filter(policy=p[0])
            ppsetids = set([pi.pset.id for pi in pis])
            if psetids is None:
                psetids = ppsetids
            else:
                psetids &= ppsetids
        return [] if psetids is None else list(psetids)


class PermissionSetManager(models.Manager):
    """Permission sets have a custom manager that folds all instances
    with the same set of policy instances (as determined by the hashes
    of the policy instances) together in the database.

    """

    def by_policies(self, policies):
        # Canonicalise input policy list to include empty variable
        # assignments where necessary, and serialise variable
        # assignments to strings for policy instance lookup.
        canonpols = [(p[0], json.dumps(p[1]))
                     if isinstance(p, tuple) else (p, '{}')
                     for p in policies]

        # Try to find an existing permission set using all the same
        # policies and variable assignments.  First step is to find a
        # list of permission set IDs using all the same policies as
        # appear in the supplied policy list.
        for psetid in policy_psets(canonpols):
            # Now, for each permission set candidate, check whether
            # the policy instance rows correspond exactly to the input
            # policy+variable assignment list.
            pset = self.get(id=psetid)
            pis = PolicyInstance.objects.filter(pset=pset)
            if len(pis) == len(canonpols):
                same = True
                for pi, canonpol in zip(pis, canonpols):
                    if pi.policy != canonpol[0] or pi.variables != canonpol[1]:
                        same = False
                        break
                if same:
                    return pset

        # If we get here, there is not an existing permission set for
        # the exact combination of policies and variable assignments
        # used here.  So we create one.

        # Make a new base permission set object: this merges the
        # policy instances into a wild card tree for fast lookup.
        def make_pol(p):
            if isinstance(p, tuple):
                return engine.PolicyBody(json=p[0].body, variables=p[1])
            else:
                return engine.PolicyBody(json=p.body)
        ptree = engine.PermissionTree(
            policies=[make_pol(p) for p in policies]
        )

        # The permission set model stores the JSON serialisation of
        # this tree structure.
        obj = self.create(data=repr(ptree))
        obj.ptree = ptree
        obj.save()

        for p, i in zip(canonpols, itertools.count()):
            PolicyInstance.objects.create(pset=obj, policy=p[0],
                                          index=i, variables=p[1])

        return obj


class PermissionSet(models.Model):
    """A permission set represents the complete set of permissions
    resulting from the composition of a sequence of policy instances.
    The permission set itself is represented as the JSON serialisation
    of a ``engine.PermissionTree`` object, and the sequence of policy
    instances is recorded using the ``PolicyInstanceAssign`` model.

    """
    # JSON serialisation of wildcard tree representation of permission
    # set.
    data = models.TextField()

    # Ordered set of policies used to generate this permission set.
    policy_assign = models.ManyToManyField(Policy, through=PolicyInstance)

    # Users to which this permission set is attached: a user has only
    # one permission set, so this is really an 1:m relation, not an
    # n:m relation.
    users = models.ManyToManyField(settings.AUTH_USER_MODEL,
                                   related_name='permissionset')
    anonymous_user = models.BooleanField(default=False)

    # Custom manager to deal with folding together permission sets
    # generated from identical sequences of policies.
    objects = PermissionSetManager()

    def tree(self):
        if not hasattr(self, 'ptree'):
            self.ptree = engine.PermissionTree(json=self.data)
        return self.ptree


@receiver(pre_delete, sender=settings.AUTH_USER_MODEL)
def user_delete(sender, instance, **kwargs):
    """Manage policies on user deletion."""
    clear_user_policies(instance)


def clear_user_policies(user):
    """Remove all policies assigned to a user (or the anonymous user if
    ``user`` is ``None``).

    """
    if user is None:
        try:
            pset = PermissionSet.objects.get(anonymous_user=True)
            pset.anonymous_user = False
            pset.save()
        except ObjectDoesNotExist:
            return
    else:
        pset = user.permissionset.first()
    if pset:
        if user is not None:
            pset.users.remove(user)
        if pset.users.count() == 0:
            pset.delete()


def assign_user_policies(user, *policies):
    """Assign a sequence of policies to a user (or the anonymous user is
    ``user`` is ``None``).  (Also installed as ``assign_policies``
    method on ``User`` model.

    """
    clear_user_policies(user)
    pset = PermissionSet.objects.by_policies(policies)
    if user is None:
        pset.anonymous_user = True
    else:
        pset.users.add(user)
    pset.save()
