# coding:utf-8

import re
from simplejson import loads, dumps, JSONDecodeError
from string import Template
import hashlib
from collections import Sequence

from .wildtree import WildTree
from .exceptions import (
    EffectException,
    PatternOverlapException,
    PolicyBodyException,
    VariableSubstitutionException)


# ------------------------------------------------------------------------------
#
#  Basic action and object representations
#

class SimpleSeparated(Sequence):
    """
    Simple sequences of strings delimited by a separator, with
    wildcarding.

    A wildcard component is represented by a ``*`` string and matches
    any single string component.  Equality comparison between
    sequences is exact comparison of components; matching between
    wildcarded components can be tested using the ``match`` method.

    """
    def __init__(self, s):
        if isinstance(s, str):
            self.components = self._split_components(s)
        elif isinstance(s, Sequence):
            self.components = s
        else:
            raise ValueError('invalid initialiser for separated sequence')

    def _split_components(self, s):
        return s.split(self.separator)

    def __len__(self):
        return len(self.components)

    def __getitem__(self, idx):
        return self.components[idx]

    def __str__(self):
        return self.separator.join(self.components)

    def __eq__(self, other):
        return self.components == other.components

    def match(self, other):
        # Two sequences match if they are the same length and
        # corresponding components are either equal, or at least one
        # is a wildcard.
        if len(self) != len(other):
            return False
        for cself, cother in zip(self.components, other.components):
            if not (cself == cother or cself == '*' or cother == '*'):
                return False
        return True


class EscapeSeparated(SimpleSeparated):
    """
    Sequences of strings delimited by a separator that can be
    backslash-escaped.  Backslashes can also be backslash-escaped; no
    other escaping mechanism is supported.

    """
    def _split_components(self, s):
        # Generate regexp lazily for each derived class so that we can
        # compile it.
        if not hasattr(self, 'regex'):
            type(self).regex = make_regex(self.separator)
        components = self.regex.split(s)[1::2]
        components = [unescape(s, self.separator) for s in components]
        return components

    def __str__(self):
        return self.separator.join([escape(s, self.separator)
                                    for s in self.components])


class Action(SimpleSeparated):
    """
    Actions are represented by period-separated sequences of elements
    (e.g. ``parcel.edit``, ``admin.assign-role``) with wildcard
    elements indicated by ``*`` (e.g. ``party.*``).  A list of
    *registered* actions is maintained to support permissions set
    queries to find the set of actions that are permitted on a
    specified object pattern.

    """
    separator = '.'

    registered = set()

    def register(action):
        """
        Action registration is used to support generating lists of
        permitted actions from a permission set and an object pattern.
        Only registered actions will be returned by such queries.

        """
        if isinstance(action, str):
            Action.register(Action(action))
        elif isinstance(action, Action):
            Action.registered.add(action)
        else:
            map(Action.register, action)


class Object(EscapeSeparated):
    """
    Objects are represented by slash-separated sequences of elements
    (e.g. ``Cadasta/Batangas/parcel/123``, ``H4H/PaP/party/118``) with
    wildcard elements indicated by ``*``
    (e.g. ``Cadasta/*/parcel/*``).  Slashes can be backslash-escaped,
    as can backslashes (e.g. ``Cadasta/Village-X\/Y/parcel/943``).

    """
    separator = '/'


# ------------------------------------------------------------------------------
#
#  Clauses and policies
#

class Clause:
    """
    A clause is a simple container for an effect ("allow" or "deny")
    and a list of non-overlapping action patterns and non-overlapping
    object patterns to which the effect applies.

    """
    def __init__(self, effect=None, action=None, object=None, dict=None):
        """
        A clause can be created either by giving explicit lists of
        ``Action`` and ``Object`` objects or by giving a dictionary
        with ``effect``, ``action`` and ``object`` keys pulled out of
        the JSON representation of a policy.

        """
        if dict is not None:
            effect = dict['effect']
            action = [Action(a) for a in dict['action']]
            object = [Object(o) for o in dict['object']]
        if effect not in ['allow', 'deny']:
            raise EffectException(effect)
        if any(a1.match(a2) for a1 in action for a2 in action if a1 != a2):
            raise PatternOverlapException('action')
        if any(o1.match(o2) for o1 in object for o2 in object if o1 != o2):
            raise PatternOverlapException('object')
        self.effect = effect
        self.action = action
        self.object = object


class Policy(Sequence):
    """
    A policy is just a sequence of clauses, possibly with a name.
    Conversion to and from JSON representations (with
    canonicalisation), and hash generation from the canonical
    representation.

    Can be composed into permission sets, so for convenience allow for
    iteration over individual (action, object) pairs (note that each
    clause can have multiple actions and objects).

    """
    def __init__(self, json, variables=None):
        try:
            d = loads(Template(json).substitute(variables))
        except JSONDecodeError as e:
            raise PolicyBodyException(lineno=e.lineno, colno=e.colno)
        except KeyError:
            raise VariableSubstitutionException()
        except ValueError:
            raise VariableSubstitutionException()
        self.version = 'version' in d and d['version'] or '2015-12-10'
        if 'clause' not in d:
            raise PolicyBodyException(msg="no policy clauses")
        self.clauses = d['clause']
        self.clauses = [Clause(dict=c) for c in self.clauses]
        self.nitems = sum([len(c.action) * len(c.object)
                           for c in self.clauses])
        self.nclauses = len(self.clauses)
        if self.version not in ['2015-12-10']:
            raise PolicyBodyException(msg="version not recognised")

    def __len__(self):
        return self.nitems

    def __getitem__(self, idx):
        return self.clauses[idx]

    def __str__(self):
        def one_clause(c):
            return {'effect': c.effect,
                    'action': [str(a) for a in c.action],
                    'object': [str(o) for o in c.object]}
        cs = [one_clause(c) for c in self.clauses]
        return dumps({'version': self.version, 'clause': cs})

    def __iter__(self):
        for c in self.clauses:
            e = c.effect
            for a in c.action:
                for o in c.object:
                    yield e, a, o

    def hash(self):
        return hashlib.md5(str(self).encode()).hexdigest()


# ------------------------------------------------------------------------------
#
#  Permission sets
#

class PermissionSet:
    """
    A permission set records, in a compact way, the permissions
    associated with a sequence of policy clauses.  The construction of
    permission sets handles the overriding of earlier clauses by later
    clauses and the treatment of wildcards in the action and object
    patterns for individual policy clauses.

    Can:
     - Create empty permissions sets.
     - Compose statements and policies into permission set.
     - Test an (action, object) pair against a permission set.
     - Determine the list of allowed actions for an object pattern from
       a permission set.

    Most of the functionality needed here is implemented in the
    ``WildTree`` class.

    """

    def __init__(self, policies=None, json=None):
        """
        Permission sets are all by default empty, with an optional list of
        policies added.  They can also be deserialised from JSON.

        """
        self.tree = WildTree(json)
        if policies is not None:
            self.add(policies=policies)

    def __repr__(self):
        """
        Serialisation to JSON.
        """
        return repr(self.tree)

    def add(self, effect=None, action=None, object=None,
            policy=None, policies=None):
        """
        Insert an individual (effect, action, object) triple or all
        triples for a policy or list of policies.

        """
        if policies is not None:
            for p in policies:
                self.add(policy=p)
        elif policy is not None:
            for e, a, o in policy:
                self.add(e, a, o)
        else:
            self.tree[action.components + object.components] = effect

    def allow(self, action, object):
        """
        Determine where a given action on a given object is allowed.
        """
        try:
            return self.tree[action.components + object.components] == 'allow'
        except KeyError:
            return False

    def permitted_actions(self, object):
        """
        Determine permitted actions for a given object pattern.
        """
        pass


# ------------------------------------------------------------------------------
#
#  Utility functions
#

def make_regex(separator):

    """
    Utility function to create regexp for matching escaped separators
    in strings.

    """
    return re.compile(r'(?:' + re.escape(separator) + r')?((?:[^' +
                      re.escape(separator) + r'\\]|\\.)+)')


def unescape(s, sep):
    """
    Unescape escaped separators and backslashes in strings.
    """
    return s.replace("\\" + sep, sep).replace("\\\\", "\\")


def escape(s, sep):
    """
    Escape unescapes separators and backslashes in strings.
    """
    return s.replace("\\", "\\\\").replace(sep, "\\" + sep)
