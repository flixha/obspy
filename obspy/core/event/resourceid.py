"""
obspy.core.event.resourceid - ResourceIdentifier
================================================
This module defines the ResourceIdentifier class and associated code.

:copyright:
    The ObsPy Development Team (devs@obspy.org)
:license:
    GNU Lesser General Public License, Version 3
    (http://www.gnu.org/copyleft/lesser.html)
"""
import re
import warnings
from contextlib import contextmanager
from copy import deepcopy
from uuid import uuid4
from weakref import WeakKeyDictionary, WeakValueDictionary

from obspy.core.util.decorator import deprecated


class _ResourceKey(object):
    """
    A private semi-singleton class used to refer id strings to objects.

    Only one instance should be created for each unique string/int, unless
    all reference are garbage collect, in which case a new instance will be
    created. Constructing instances through the get_resource_key class method
    is required to ensure this behavior.

    This class allows the python gc to handle cleanup of the
    ResourceIdentifier stored class state rather than manual reference
    counting as was implemented before.
    """
    # define a mapping from a resource string to a singleton instance
    _singleton_cache = WeakValueDictionary()

    def __deepcopy__(self, memodict={}):
        memodict[id(self)] = self
        return self

    def __copy__(self):
        return self

    @classmethod
    def get_resource_key(cls, unique_id):
        if unique_id not in _ResourceKey._singleton_cache:
            single = _ResourceKey()
            _ResourceKey._singleton_cache[unique_id] = single
        return _ResourceKey._singleton_cache[unique_id]


class _ResourceKeyDescriptor(object):
    """
    A private descriptor for initializing _Resource_Key instances.
    """

    def __init__(self, name, default=None):
        self.name = name + '__'
        self.default = default

    def __get__(self, instance, owner):
        return getattr(instance, self.name, self.default)

    def __set__(self, instance, value):
        # if an object was passed, use the id of the object for hash
        if value is not None:
            if not isinstance(value, (int, str)):
                value = id(value)
            setattr(instance, self.name, _ResourceKey.get_resource_key(value))


class ResourceIdentifier(object):
    r"""
    Unique identifier referring to a resource.

    In QuakeML many elements and types can have a unique id that other elements
    use to refer to it. This is called a ResourceIdentifier and it is used for
    the same purpose in the obspy.core.event classes. The id must be a string.

    In QuakeML it has to be of the following regex form::

        (smi|quakeml):[\w\d][\w\d\-\.\*\(\)_~']{2,}/[\w\d\-\.\*\(\)_~']
        [\w\d\-\.\*\(\)\+\?_~'=,;#/&]*

    e.g.

    * ``smi:sub.website.org/event/12345678``
    * ``quakeml:google.org/pick/unique_pick_id``

    smi stands for "seismological meta-information".

    :type id: str, optional
    :param id: A string to uniquely identify a resource. If no resource_id
        is given, uuid.uuid4() will be used to create one which assures
        uniqueness within the current Python run. If no fixed id is provided,
        the ID will be built from prefix and a random uuid hash. The random
        hash can be regenerated by the referred object automatically if it
        gets changed.
    :type prefix: str, optional
    :param prefix: An optional identifier that will be put in front of any
        automatically created resource id. The prefix will only have an effect
        if `id` is not specified (for a fixed ID string). Makes automatically
        generated resource ids more reasonable. By default "smi:local" is used
        which ensures a QuakeML compliant resource identifier.
    :type referred_object: object, optional
    :param referred_object: The object (resource) to which this instance
        refers. All instances created with the same resource_id will be able
        to access the object as long as at least one instance actually has a
        reference to it. Additionally, ResourceIdentifier instances that have
        the same id but refer to different objects will still return the
        correct referred object, provided it doesn't get garbage collected.
        If the referred object no longer exists the last object registered
        with the same id will be returned, or None if no such object exists.
    :type parent: hashable
    :param parent:
        The parent to use as a namespace for the resource identifier. This
        allows potentially interconnected resource identifiers to be sensibly
        grouped together, ensuring that objects belonging to the same parent
        are returned by resource ids of the parent. Used primarily to ensure
        resource_ids in an event refer to other objects in the same event.
        All resource ids must be unique within the parent namespace.

    .. rubric:: General Usage

    >>> ResourceIdentifier('2012-04-11--385392')
    ResourceIdentifier(id="2012-04-11--385392")
    >>> # If 'id' is not specified it will be generated automatically.
    >>> ResourceIdentifier()  # doctest: +ELLIPSIS
    ResourceIdentifier(id="smi:local/...")
    >>> # Supplying a prefix will simply prefix the automatically generated ID
    >>> ResourceIdentifier(prefix='event')  # doctest: +ELLIPSIS
    ResourceIdentifier(id="event/...")

    ResourceIdentifiers can, and oftentimes should, carry a reference to the
    object they refer to. This is a weak reference which means that if the
    object get deleted or runs out of scope, e.g. gets garbage collected, the
    reference will cease to exist.

    >>> from obspy.core.event import Event
    >>> event = Event()
    >>> import sys
    >>> ref_count = sys.getrefcount(event)
    >>> res_id = ResourceIdentifier(referred_object=event)
    >>> # The reference does not changed the reference count of the object.
    >>> print(ref_count == sys.getrefcount(event))
    True
    >>> # It actually is the same object.
    >>> print(event is res_id.get_referred_object())
    True
    >>> # Deleting it, or letting the garbage collector handle the object will
    >>> # invalidate the reference.
    >>> del event
    >>> print(res_id.get_referred_object())  # doctest: +SKIP
    None

    The most powerful ability (and reason why one would want to use a resource
    identifier class in the first place) is that once a ResourceIdentifier with
    an attached referred object has been created, any other ResourceIdentifier
    instances with the same ID can retrieve that object. This works
    across all ResourceIdentifiers that have been instantiated within one
    Python run.
    This enables, e.g. the resource references between the different QuakeML
    elements to work in a rather natural way.

    >>> event_object = Event()
    >>> obj_id = id(event_object)
    >>> res_id = "obspy.org/event/test"
    >>> ref_a = ResourceIdentifier(res_id)
    >>> # The object is refers to cannot be found yet. Because no instance that
    >>> # an attached object has been created so far.
    >>> print(ref_a.get_referred_object())
    None
    >>> # This instance has an attached object.
    >>> ref_b = ResourceIdentifier(res_id, referred_object=event_object)
    >>> ref_c = ResourceIdentifier(res_id)
    >>> # All ResourceIdentifiers will refer to the same object.
    >>> assert ref_a.get_referred_object() is event_object
    >>> assert ref_b.get_referred_object() is event_object
    >>> assert ref_c.get_referred_object() is event_object

    Resource identifiers are bound to an object once the get_referred_object
    method has been called. The results is that get_referred_object will
    always return the same object it did on the first call as long as the
    object still exists. If the bound object gets garage collected a warning
    will be issued and another object with the same resource_id will be
    returned (if one exists). If no other object is associated with the same
    resource_id, an additional warning will be issued and None returned.

    >>> from obspy import UTCDateTime
    >>> res_id = 'obspy.org/tests/test_resource_doc_example'
    >>> obj_a = UTCDateTime(10)
    >>> obj_b = UTCDateTime(10)
    >>> ref_a = ResourceIdentifier(res_id, referred_object=obj_a)
    >>> ref_b = ResourceIdentifier(res_id, referred_object=obj_b)
    >>> assert ref_a.get_referred_object() == ref_b.get_referred_object()
    >>> assert ref_a.get_referred_object() is not ref_b.get_referred_object()
    >>> assert ref_a.get_referred_object() is obj_a
    >>> assert ref_b.get_referred_object() is obj_b
    >>> del obj_b  # obj_b gets garbage collected
    >>> assert ref_b.get_referred_object() is obj_a  # doctest: +SKIP
    >>> del obj_a  # now no object with res_id exists
    >>> assert ref_b.get_referred_object() is None  # doctest: +SKIP

    ResourceIdentifiers are considered identical if the IDs are
    the same.

    >>> # Create two different resource identifiers.
    >>> res_id_1 = ResourceIdentifier()
    >>> res_id_2 = ResourceIdentifier()
    >>> res_id_3 = ResourceIdentifier(id=res_id_2.id)
    >>> assert res_id_1 != res_id_2
    >>> assert res_id_2 == res_id_3

    ResourceIdentifier instances can be used as dictionary keys.

    >>> dictionary = {}
    >>> res_id = ResourceIdentifier(id="foo")
    >>> dictionary[res_id] = "bar1"
    >>> # The same ID can still be used as a key.
    >>> dictionary["foo"] = "bar2"
    >>> items = sorted(dictionary.items(), key=lambda kv: kv[1])
    >>> for k, v in items:  # doctest: +ELLIPSIS
    ...     print(repr(k), v)
    ResourceIdentifier(id="foo") bar1
    ...'foo' bar2

    Because ResourceIdentifier instances are hashed based on their id
    attribute, you should never change it once it has been set. Create a new
    ResourceIdentifier object instead.
    """
    # Class (not instance) attributes that keeps track of all resource
    # identifier instances throughout one Python run. Will only store weak
    # references and therefore does not interfere with the garbage collection.
    # DO NOT CHANGE THIS FROM OUTSIDE THE CLASS. Use the _debug_class_state
    # method for temporarily altering these for testing or debugging.

    # A dict for keeping track of parent/object specific references.
    # weak_key, weak_key, weak_value
    # {parent_key: {resource_key: object_id}}
    _parent_id_tree = WeakKeyDictionary()

    # Dict of list to keep track of the order in which resource_ids are
    # assigned to object_ids.
    # {resource_id: [object_id, object_id, ...]}
    _id_order = WeakKeyDictionary()

    # A weak value dict mapping object ids (not resource ids) to objects.
    # {object_id: object}
    _id_object_map = WeakValueDictionary()

    # A get objects hook to allow plugging in custom logic for finding objects
    # with by resource_id if they are not found via normal means.
    _get_object_hook = []

    # Set default _ResourceKey attributes and object_id.
    _parent_key = _ResourceKeyDescriptor('_parent_key')
    _resource_key = _ResourceKeyDescriptor('_resource_key')
    _object_id = None

    def __init__(self, id=None, prefix="smi:local", referred_object=None,
                 parent=None):
        # Create a resource id if None is given and possibly use a prefix.
        if id is None:
            self.fixed = False
            self._prefix = prefix
            self._uuid = str(uuid4())
        elif isinstance(id, ResourceIdentifier):
            self.__dict__.update(id.__dict__)
            return
        else:
            self.fixed = True
            self.id = id
        # get resource and parent _ResourceKey singletons
        self._resource_key = self.id
        self._parent_key = parent
        # set referred object if one was provided.
        if referred_object is not None:
            self.set_referred_object(referred_object)

    def get_referred_object(self):
        """
        Returns the object associated with the resource identifier.

        This works as long as at least one ResourceIdentifier with the same
        ID as this instance has an associated object. If not, this method will
        return None.
        """
        try:
            out = ResourceIdentifier._id_object_map[self._object_key]
        except KeyError:
            out = self._get_similar_referred_object()
        if out is not None:
            return out
        else:  # If no object was found iterate get_object hooks.
            for hook in self._get_object_hook:
                out = hook(self.id)
                if out is not None:
                    self.set_referred_object(out)
                    return out

    def _get_similar_referred_object(self):
        """
        Find an object with the same resource id.

        If the resource_identifier instance is not bound to a specific object,
        or the bound object has been garbage collected, try to find another
        object that was assigned the same resource_id.

        The parent_id_tree will be scanned first to see if any object_ids
        have been assigned to the same resource_id in the parent scope. If
        not simply use the last object assigned the resource_id. If no object
        is found return None.
        """
        # Warn if resource_id was bound but its object got gc'ed.
        if self._object_id is not None:
            msg = ("The object with identity of: %d  and id of %s no longer "
                   "exists, trying to find an object with the same id"
                   ) % (self._object_id, self.id)
            warnings.warn(msg, UserWarning)
        # try to get the object_id from the parent_id_tree
        obj = self._get_object_from_parent_scope()
        if obj is None:
            # else try to find the last object assigned the same resource_id
            obj = self._get_newest_object_with_same_resource_id()
        # if an object was found bind it to resource_id and return it
        if obj is not None:
            self.set_referred_object(obj, warn=False)
        return obj

    def _get_newest_object_with_same_resource_id(self):
        """
        Return the newest object which has been bound to the same resource_id.
        If No such object exists return None.
        """
        try:
            rid_list = ResourceIdentifier._id_order[self._resource_key]
        except KeyError:  # no existing object is assigned to this resource_id
            return None
        while len(rid_list):
            try:
                obj_key = ResourceIdentifier._id_order[self._resource_key][-1]
            except KeyError:
                return None
            else:
                try:
                    obj = ResourceIdentifier._id_object_map[obj_key]
                except KeyError:  # Object got gc'ed or was not defined.
                    rid_list.pop()  # Remove last element in list.
                    continue
                # Ensure the current resource_id matches the old one, there
                # can, in rare cases, be a mismatch due to issue #2278.
                if obj_key[-1] != self.id:
                    rid_list.pop()
                    continue
                return obj

    def _get_object_from_parent_scope(self):
        """
        Find an object in the same parent scope with the same resource_id. If
        No such object is found return None.
        """
        id_tree = ResourceIdentifier._parent_id_tree
        try:
            obj_key = id_tree[self._parent_key][self._resource_key]
        except (KeyError, TypeError):
            pass
        else:
            try:
                obj = ResourceIdentifier._id_object_map[obj_key]
            except KeyError:
                pass
            else:
                if obj_key[-1] == self.id:
                    return obj

    def set_referred_object(self, referred_object, warn=True, parent=None):
        """
        Bind an object to the ResourceIdentifier instance.

        Also allows the object to be bound to a parent scope. Will emit a
        warning if referred_object is not equal to the last object referred
        to by the same resource_id, or, if the resource_id does not refer to
        an object that currently exists, the last object assigned to the same
        resource id code.

        :param referred_object: The object to which the resource id refers.
        :type referred_object: object
        :param warn:
            If True, issue a warning if the referred_object is not equal to
            the last object assigned the same resource_id.
        :type warn: bool
        :param parent:
            An object or int (id) to which the resource_id should be scoped.
            Used, for example, to ensure the all resource ids belonging to an
            event object are event-scoped.
        :type parent: object, int
        """

        # Get the last object bound to this instance of ResourceIdentifier or
        # if there is None, get the last referred_object assigned the same
        # resource_id code.
        id_order = ResourceIdentifier._id_order
        old = ResourceIdentifier._id_object_map.get(self._object_key, None)
        if old is None:  # Look for last object with same resource id.
            try:
                old_obj_id_key = id_order[self._resource_key][-1]
                old = ResourceIdentifier._id_object_map[old_obj_id_key]
            except (KeyError, IndexError):
                pass
        if warn and old is not None and old != referred_object:
            msg = ('Warning, binding object to resource ID %s which '
                   'is not equal to the last object bound to this '
                   'resource_id') % self.id
            warnings.warn(msg, UserWarning)
        # Set the object id to the new object, and update parent scoping tree.
        self._object_id = id(referred_object)
        if parent is not None or self._parent_key is not None:
            if parent is not None:
                self._parent_key = parent
            id_tree = ResourceIdentifier._parent_id_tree
            if self._parent_key not in id_tree:
                id_tree[self._parent_key] = WeakKeyDictionary()
            id_tree[self._parent_key][self._resource_key] = self._object_key
        # Set the new id in id map and append referred_object to id_order.
        ResourceIdentifier._id_object_map[self._object_key] = referred_object
        if self._resource_key not in id_order:
            id_order[self._resource_key] = []
        id_order[self._resource_key].append(self._object_key)

    @deprecated()
    def convert_id_to_quakeml_uri(self, authority_id="local"):
        """
        Converts the current ID to a valid QuakeML URI.

        This method is deprecated, use :meth:`get_quakeml_id` instead.

        Only an invalid QuakeML ResourceIdentifier string it will be converted
        to a valid one.  Otherwise nothing will happen but after calling this
        method the user can be sure that the ID is a valid QuakeML URI.

        The resulting ID will be of the form
            smi:authority_id/prefix/resource_id

        :type authority_id: str, optional
        :param authority_id: The base url of the resulting string. Defaults to
            ``"local"``.
        """
        self.id = self.get_quakeml_uri_str(authority_id=authority_id)

    def get_quakeml_id(self, authority_id="local"):
        """
        Returns a resource id with a valid QuakeML URI.

        Only an invalid QuakeML ResourceIdentifier string it will be converted
        to a valid one.  Otherwise the returned resource id will be identical
        to the original.

        The new resource id will have the same referred object as the
        original.

        The resulting ID will be of the form
            smi:authority_id/prefix/resource_id

        :type authority_id: str, optional
        :param authority_id: The base url of the resulting string. Defaults to
            ``"local"``.
        :return: A new ResourceIdentifier instance with a valid quakeml uri.
        """
        new_id = self.get_quakeml_uri_str(authority_id=authority_id)
        rid = ResourceIdentifier(new_id)
        referred_obj = self.get_referred_object()
        if referred_obj is not None:
            rid.set_referred_object(referred_obj, warn=False,
                                    parent=self._parent_key)
        return rid

    @deprecated()
    def get_quakeml_uri(self, authority_id="local"):
        """
        This method is deprecated, use :meth:`.get_quakeml_uri_str` instead.
        """
        return self.get_quakeml_uri_str(authority_id=authority_id)

    def get_quakeml_uri_str(self, authority_id="local"):
        """
        Returns an id with a valid QuakeML URI.

        If no valid QuakeML is possible a ValueError is raised.

        :type authority_id: str, optional
        :param authority_id: The base url of the resulting string. Defaults to
            ``"local"``.
        :return: A new ResourceIdentifier instance with a valid quakeml uri.

        >>> res_id = ResourceIdentifier("some_id")
        >>> print(res_id.get_quakeml_uri_str())
        smi:local/some_id
        >>> # Did not change the actual resource id.
        >>> print(res_id.id)
        some_id
        """
        id = self.id
        if str(id).strip() == "":
            id = str(uuid4())

        regex = r"^(smi|quakeml):[\w\d][\w\d\-\.\*\(\)_~']{2,}/[\w\d\-\." + \
                r"\*\(\)_~'][\w\d\-\.\*\(\)\+\?_~'=,;#/&]*$"
        result = re.match(regex, str(id))
        if result is not None:
            return id
        id = 'smi:%s/%s' % (authority_id, str(id))
        # Check once again just to be sure no weird symbols are stored in the
        # ID.
        result = re.match(regex, id)
        if result is None:
            msg = (
                "The id '%s' is not a valid QuakeML resource "
                "identifier. ObsPy tried modifying it to '%s' but it is still "
                "not valid. Please make sure all resource ids are either "
                "valid or can be made valid by prefixing them with "
                "'smi:<authority_id>/'. Valid ids are specified in the "
                "QuakeML manual section 3.1 and in particular exclude colons "
                "for the final part." % (self.id, id))
            raise ValueError(msg)
        return id

    def copy(self):
        """
        Returns a copy of the ResourceIdentifier.
        >>> res_id = ResourceIdentifier()
        >>> res_id_2 = res_id.copy()
        >>> print(res_id is res_id_2)
        False
        >>> print(res_id == res_id_2)
        True
        """
        return deepcopy(self)

    def __deepcopy__(self, memodict={}):
        new = ResourceIdentifier.__new__(ResourceIdentifier)
        new.__dict__.update(self.__dict__)
        # clear object_id upon copying resource_ids
        new._parent_key = None
        memodict[id(self)] = new
        return new

    def __setstate__(self, state):
        """
        Make sure the resource_key follows the singleton pattern.
        """
        self.__dict__ = state
        self._parent_key = None
        self._resource_key = _ResourceKey.get_resource_key(self.id)

    @property
    def _object_key(self):
        """
        The value used to identify objects bound to resource_ids.

        Uses a hash of both the object id and resource id, see #2278.
        """
        return self._object_id, self.id

    @property
    def id(self):
        """
        Unique identifier of the current instance.
        """
        if self.fixed:
            return self.__dict__.get("id")
        else:
            id = self.prefix
            if not id.endswith("/"):
                id += "/"
            id += self.uuid
            return id

    @id.deleter
    def id(self):
        msg = "The resource id cannot be deleted."
        raise Exception(msg)

    @id.setter
    def id(self, value):
        self.fixed = True
        if not isinstance(value, str):
            msg = "attribute id needs to be a string."
            raise TypeError(msg)
        if '_resource_key__' in self.__dict__:
            msg = ('overwritting the id attribute of a ResourceIdentifier'
                   'object is very dangerous and will raise an exception in '
                   'a future version of obspy')
            warnings.warn(msg, UserWarning)
        self.__dict__["id"] = value

    @property
    def prefix(self):
        return self._prefix

    @prefix.deleter
    def prefix(self):
        self._prefix = ""

    @prefix.setter
    def prefix(self, value):
        if not isinstance(value, str):
            msg = "prefix id needs to be a string."
            raise TypeError(msg)
        self._prefix = value

    @property
    def uuid(self):
        return self._uuid

    @uuid.deleter
    def uuid(self):
        """
        Deleting is uuid hash is forbidden and will not work.
        """
        msg = "The uuid cannot be deleted."
        raise Exception(msg)

    @uuid.setter
    def uuid(self, value):  # @UnusedVariable
        """
        Setting is uuid hash is forbidden and will not work.
        """
        msg = "The uuid cannot be set manually."
        raise Exception(msg)

    @property
    def resource_id(self):
        return self.id

    @resource_id.deleter
    def resource_id(self):
        del self.id

    @resource_id.setter
    def resource_id(self, value):
        self.id = value

    def __str__(self):
        return self.id

    def _repr_pretty_(self, p, cycle):
        p.text(str(self))

    def __repr__(self):
        return 'ResourceIdentifier(id="%s")' % self.id

    def __eq__(self, other):
        if self.id == other:
            return True
        if not isinstance(other, ResourceIdentifier):
            return False
        if self.id == other.id:
            return True
        return False

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        """
        Uses the same hash as the resource id. This means that class instances
        can be used in dictionaries and other hashed types.
        Both the object and it's id can still be independently used as
        dictionary keys.
        """
        # "Salt" the hash with a string so the hash of the object and a
        # string identical to the id can both be used as individual
        # dictionary keys.
        return hash("RESOURCE_ID") + self.id.__hash__()

    # Like the weakref.ref class, calling a resource id instance can
    # return the referred object, if in scope, else None.
    __call__ = get_referred_object

    @deprecated()
    def regenerate_uuid(self):
        """
        Regenerates the uuid part of the ID. Does nothing for resource
        identifiers with a user-set, fixed id.
        """
        self._uuid = str(uuid4())

    @classmethod
    def register_get_object_hook(cls, get_object_callable):
        """
        Register a callable to return referred object if normal means fail.

        This is useful, for example, to allow the resource_identifier to
        create objects from entries in a database that do not yet have an
        in-memory representation.

        :param get_object_callable:
            Any callable that takes a resource id string and returns an
            object.
        :type get_object_callable: callable
        """
        cls._get_object_hook.append(get_object_callable)

    @classmethod
    def remove_get_object_hook(cls, get_object_callable):
        """
        Remove a callable from the registered get_object hooks.

        :param get_object_callable:
            The callable to remove from the get_object hook registry.
        :type get_object_callable: callable, optional
        """
        if get_object_callable is not None:
            try:
                cls._get_object_hook.remove(get_object_callable)
            except ValueError:  # Pass if get_object_callable is not in list.
                pass
        else:
            cls._get_object_hook.clear()

    @classmethod
    def _bind_class_state(cls, state_dict):
        """
        Bind the state contained in state_dict to ResourceIdentifier class.
        """
        cls._parent_id_tree = state_dict['parent_id_tree']
        cls._id_order = state_dict['id_order']
        cls._id_object_map = state_dict['id_object_map']
        cls._get_referred_object_hook = state_dict['get_object_hook']

    @classmethod
    @contextmanager
    def _debug_class_state(cls):
        """
        Context manager for debugging the class level state for Resource Ids.

        Replaces the current resource_id and unbound mappings returning
        a dictionary with the new mappings as values and "rdict", and
        "unbound" as keys. This function restores original mappings upon exit.
        """
        # get current class state
        old_state = dict(
            parent_id_tree=cls._parent_id_tree,
            id_order=cls._id_order,
            id_object_map=cls._id_object_map,
            get_object_hook=cls._get_object_hook,
        )
        # init new class state
        new_state = dict(
            parent_id_tree=WeakKeyDictionary(),
            id_order=WeakKeyDictionary(),
            id_object_map=WeakValueDictionary(),
            get_object_hook=[],
        )
        # bind new state and return dict
        cls._bind_class_state(new_state)
        yield new_state
        # reset prior state
        cls._bind_class_state(old_state)


if __name__ == '__main__':
    import doctest
    doctest.testmod(exclude_empty=True)
