from rest_framework.serializers import Serializer, HyperlinkedIdentityField, ValidationError
from rest_framework.relations import PrimaryKeyRelatedField

from netbox.api import ChoiceField, WritableNestedSerializer, ValidatedModelSerializer
from dcim.api.nested_serializers import NestedSiteSerializer, NestedDeviceSerializer
from tenancy.api.nested_serializers import NestedTenantSerializer
from extras.api.nested_serializers import NestedTagSerializer
from ipam.api.nested_serializers import NestedIPAddressSerializer


try:
    from extras.api.customfields import CustomFieldModelSerializer
except ImportError:
    from netbox.api.serializers import CustomFieldModelSerializer

from netbox_bgp.models import (
    ASN, ASNStatusChoices, BGPSession, SessionStatusChoices, RoutingPolicy, BGPPeerGroup,
    Community
)


class TaggedObjectSerializer(Serializer):
    tags = NestedTagSerializer(many=True, required=False)

    def create(self, validated_data):
        tags = validated_data.pop('tags', None)
        instance = super().create(validated_data)

        if tags is not None:
            return self._save_tags(instance, tags)
        return instance

    def update(self, instance, validated_data):
        tags = validated_data.pop('tags', None)
        # Cache tags on instance for change logging
        instance._tags = tags or []

        instance = super().update(instance, validated_data)
        if tags is not None:
            return self._save_tags(instance, tags)
        return instance

    def _save_tags(self, instance, tags):
        if tags:
            instance.tags.set(*[t.name for t in tags])
        else:
            instance.tags.clear()
        return instance


class SerializedPKRelatedField(PrimaryKeyRelatedField):
    def __init__(self, serializer, **kwargs):
        self.serializer = serializer
        self.pk_field = kwargs.pop('pk_field', None)
        super().__init__(**kwargs)

    def to_representation(self, value):
        return self.serializer(value, context={'request': self.context['request']}).data


class ASNSerializer(TaggedObjectSerializer, CustomFieldModelSerializer):
    status = ChoiceField(choices=ASNStatusChoices, required=False)
    site = NestedSiteSerializer(required=False, allow_null=True)
    tenant = NestedTenantSerializer(required=False, allow_null=True)

    def validate(self, attrs):
        try:
            number = attrs['number']
            tenant = attrs.get('tenant')
        except KeyError:
            # this is patch
            return attrs
        if ASN.objects.filter(number=number, tenant=tenant).exists():
            raise ValidationError(
                {'error': 'Asn with this Number and Tenant already exists.'}
            )
        return attrs

    class Meta:
        ref_name = 'BGP_ASN'
        model = ASN
        fields = ['number', 'id', 'display', 'status', 'description', 'custom_fields', 'site', 'tenant', 'tags']


class NestedASNSerializer(WritableNestedSerializer):
    url = HyperlinkedIdentityField(view_name='plugins:netbox_bgp:asn')

    class Meta:
        ref_name = 'BGP_ASN_Nested'
        model = ASN
        fields = ['id', 'url', 'number', 'description']


class RoutingPolicySerializer(TaggedObjectSerializer, CustomFieldModelSerializer):
    class Meta:
        model = RoutingPolicy
        fields = '__all__'


class NestedRoutingPolicySerializer(WritableNestedSerializer):
    url = HyperlinkedIdentityField(view_name='plugins:netbox_bgp:routing_policy')

    class Meta:
        model = RoutingPolicy
        fields = ['id', 'url', 'name', 'description']


class BGPPeerGroupSerializer(TaggedObjectSerializer, CustomFieldModelSerializer):
    import_policies = SerializedPKRelatedField(
        queryset=RoutingPolicy.objects.all(),
        serializer=NestedRoutingPolicySerializer,
        required=False,
        allow_null=True,
        many=True
    )
    export_policies = SerializedPKRelatedField(
        queryset=RoutingPolicy.objects.all(),
        serializer=NestedRoutingPolicySerializer,
        required=False,
        allow_null=True,
        many=True
    )

    class Meta:
        model = BGPPeerGroup
        fields = '__all__'


class NestedBGPPeerGroupSerializer(WritableNestedSerializer):
    url = HyperlinkedIdentityField(view_name='plugins:netbox_bgp:peergroup')

    class Meta:
        model = BGPPeerGroup
        fields = ['id', 'url', 'name', 'description']
        validators = []


class BGPSessionSerializer(TaggedObjectSerializer, CustomFieldModelSerializer):
    status = ChoiceField(choices=SessionStatusChoices, required=False)
    site = NestedSiteSerializer(required=False, allow_null=True)
    tenant = NestedTenantSerializer(required=False, allow_null=True)
    device = NestedDeviceSerializer(required=False, allow_null=True)
    local_address = NestedIPAddressSerializer(required=True, allow_null=False)
    remote_address = NestedIPAddressSerializer(required=True, allow_null=False)
    local_as = NestedASNSerializer(required=True, allow_null=False)
    remote_as = NestedASNSerializer(required=True, allow_null=False)
    peer_group = NestedBGPPeerGroupSerializer(required=False, allow_null=True)
    import_policies = SerializedPKRelatedField(
        queryset=RoutingPolicy.objects.all(),
        serializer=NestedRoutingPolicySerializer,
        required=False,
        allow_null=True,
        many=True
    )
    export_policies = SerializedPKRelatedField(
        queryset=RoutingPolicy.objects.all(),
        serializer=NestedRoutingPolicySerializer,
        required=False,
        allow_null=True,
        many=True
    )

    class Meta:
        model = BGPSession
        fields = '__all__'
        validators = []

    def validate(self, attrs):
        qs = BGPSession.objects.filter(
            device=attrs.get('device'),
            local_as=attrs.get('local_as'),
            local_address=attrs.get('local_address'),
            remote_as=attrs.get('remote_as'),
            remote_address=attrs.get('remote_address'),
        )
        if qs.exists():
            raise ValidationError(
                {'error': 'BGP Session with this Device, Local address, Local AS, Remote address and Remote AS already exists.'}
            )
        return attrs

    def to_representation(self, instance):
        ret = super().to_representation(instance)

        if instance is not None:
            if instance.peer_group:
                for pol in instance.peer_group.import_policies.difference(instance.import_policies.all()):
                    ret['import_policies'].append(
                        NestedRoutingPolicySerializer(pol, context={'request': self.context['request']}).data
                    )
                for pol in instance.peer_group.export_policies.difference(instance.export_policies.all()):
                    ret['export_policies'].append(
                        NestedRoutingPolicySerializer(pol, context={'request': self.context['request']}).data
                    )
        return ret


class CommunitySerializer(TaggedObjectSerializer, ValidatedModelSerializer):
    status = ChoiceField(choices=ASNStatusChoices, required=False)
    tenant = NestedTenantSerializer(required=False, allow_null=True)

    class Meta:
        model = Community
        fields = ['id', 'value', 'status', 'description', 'tenant', 'tags']
