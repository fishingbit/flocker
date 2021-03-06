# Copyright Hybrid Logic Ltd.  See LICENSE file for details.

"""
Tests for :module:`flocker.node.script`.
"""
import netifaces

from zope.interface.verify import verifyObject

from twisted.internet.defer import Deferred
from twisted.trial.unittest import SynchronousTestCase
from twisted.application.service import Service

from ...volume.testtools import make_volume_options_tests
from ...common.script import ICommandLineScript

from ..script import (
    ZFSAgentOptions, ZFSAgentScript, AgentScript, ContainerAgentOptions,
    AgentServiceFactory, DatasetAgentOptions)
from .._loop import AgentLoopService
from .._deploy import P2PManifestationDeployer
from ...testtools import MemoryCoreReactor


class ZFSAgentScriptTests(SynchronousTestCase):
    """
    Tests for ``ZFSAgentScript``.
    """
    def test_main_starts_service(self):
        """
        ``ZFSAgentScript.main`` starts the given service.
        """
        service = Service()
        options = ZFSAgentOptions()
        options.parseOptions([b"127.0.0.1"])
        ZFSAgentScript().main(MemoryCoreReactor(), options, service)
        self.assertTrue(service.running)

    def test_no_immediate_stop(self):
        """
        The ``Deferred`` returned from ``ZFSAgentScript`` is not fired.
        """
        script = ZFSAgentScript()
        options = ZFSAgentOptions()
        options.parseOptions([b"127.0.0.1"])
        self.assertNoResult(script.main(MemoryCoreReactor(), options,
                                        Service()))

    def test_starts_convergence_loop(self):
        """
        ``ZFSAgentScript.main`` starts a convergence loop service.
        """
        service = Service()
        options = ZFSAgentOptions()
        options.parseOptions([b"--destination-port", b"1234", b"10.0.0.1"])
        test_reactor = MemoryCoreReactor()
        ZFSAgentScript().main(test_reactor, options, service)
        parent_service = service.parent
        # P2PManifestationDeployer is difficult to compare automatically,
        # so do so manually:
        deployer = parent_service.deployer
        parent_service.deployer = None
        self.assertEqual((parent_service, deployer.__class__,
                          deployer.volume_service,
                          parent_service.running),
                         (AgentLoopService(reactor=test_reactor,
                                           deployer=None,
                                           host=u"10.0.0.1",
                                           port=1234),
                          P2PManifestationDeployer, service, True))


def get_all_ips():
    """
    Find all IPs for this machine.

    :return: ``list`` of IP addresses (``bytes``).
    """
    ips = []
    interfaces = netifaces.interfaces()
    for interface in interfaces:
        addresses = netifaces.ifaddresses(interface)
        ipv4 = addresses.get(netifaces.AF_INET)
        if not ipv4:
            continue
        for address in ipv4:
            ips.append(address['addr'])
    return ips


class AgentServiceFactoryTests(SynchronousTestCase):
    """
    Tests for ``AgentServiceFactory``.
    """
    def test_get_service(self):
        """
        ``AgentServiceFactory.get_service`` creates ``AgentLoopService``
        configured with the destination given by the options.
        """
        deployer = object()

        def factory(**kw):
            if set(kw.keys()) != {"node_uuid", "hostname"}:
                raise TypeError("wrong arguments")
            return deployer

        reactor = MemoryCoreReactor()
        options = DatasetAgentOptions()
        options.parseOptions([
            b"--destination-port", b"1234", b"10.0.0.2",
        ])
        service_factory = AgentServiceFactory(
            deployer_factory=factory
        )
        self.assertEqual(
            AgentLoopService(
                reactor=reactor,
                deployer=deployer,
                host=b"10.0.0.2",
                port=1234,
            ),
            service_factory.get_service(reactor, options)
        )

    def test_deployer_factory_called_with_ip(self):
        """
        ``AgentServiceFactory.main`` calls its ``deployer_factory`` with one
        of the node's IPs.
        """
        spied = []

        def deployer_factory(node_uuid, hostname):
            spied.append(hostname)
            return object()

        reactor = MemoryCoreReactor()
        options = DatasetAgentOptions()
        options.parseOptions([b"10.0.0.2"])
        agent = AgentServiceFactory(deployer_factory=deployer_factory)
        agent.get_service(reactor, options)
        self.assertIn(spied[0], get_all_ips())


class AgentScriptTests(SynchronousTestCase):
    """
    Tests for ``AgentScript``.
    """
    def setUp(self):
        self.reactor = MemoryCoreReactor()
        self.options = DatasetAgentOptions()

    def test_interface(self):
        """
        ``AgentScript`` instances provide ``ICommandLineScript``.
        """
        self.assertTrue(
            verifyObject(
                ICommandLineScript,
                AgentScript(
                    service_factory=lambda reactor, options: Service()
                )
            )
        )

    def test_service_factory_called_with_main_arguments(self):
        """
        ``AgentScript`` calls the ``service_factory`` with the reactor
        and options passed to ``AgentScript.main``.
        """
        args = []
        service = Service()

        def service_factory(reactor, options):
            args.append((reactor, options))
            return service

        agent = AgentScript(service_factory=service_factory)
        agent.main(self.reactor, self.options)
        self.assertEqual([(self.reactor, self.options)], args)

    def test_main_starts_service(self):
        """
        ```AgentScript.main`` starts the service created by its
        ``service_factory`` .
        """
        service = Service()
        agent = AgentScript(
            service_factory=lambda reactor, options: service
        )
        agent.main(self.reactor, self.options)
        self.assertTrue(service.running)

    def test_main_stops_service(self):
        """
        When the reactor passed to ``AgentScript.main`` shuts down, the
        service created by the ``service_factory`` is stopped.
        """
        service = Service()
        agent = AgentScript(
            service_factory=lambda reactor, options: service
        )
        agent.main(self.reactor, self.options)
        self.reactor.fireSystemEvent("shutdown")
        self.assertFalse(service.running)

    def test_main_deferred_fires_after_service_stop(self):
        """
        The ``Deferred`` returned by ``AgentScript.main`` doesn't fire
        until after the ``Deferred`` returned by the ``stopService`` method of
        the service created by ``service_factory``.
        """
        shutdown_deferred = Deferred()

        class SlowShutdown(Service):
            def stopService(self):
                return shutdown_deferred

        service = SlowShutdown()
        agent = AgentScript(
            service_factory=lambda reactor, options: service
        )
        stop_deferred = agent.main(self.reactor, self.options)
        self.reactor.fireSystemEvent("shutdown")
        self.assertNoResult(stop_deferred)
        shutdown_deferred.callback(None)
        self.assertIs(None, self.successResultOf(stop_deferred))


def make_amp_agent_options_tests(options_type):
    """
    Create a test case which contains the tests that should apply to any and
    all convergence agents (dataset or container).

    :param options_type: An ``Options`` subclass  to be tested.

    :return: A ``SynchronousTestCase`` subclass defining tests for that options
        type.
    """

    class Tests(SynchronousTestCase):
        def setUp(self):
            self.options = options_type()

        def test_default_port(self):
            """
            The default AMP destination port configured by the command line
            options is 4524.
            """
            self.options.parseOptions([b"127.0.0.1"])
            self.assertEqual(self.options["destination-port"], 4524)

        def test_custom_port(self):
            """
            The ``--destination-port`` command-line option allows configuring
            the destination port.
            """
            self.options.parseOptions([b"--destination-port", b"1234",
                                       b"127.0.0.1"])
            self.assertEqual(self.options["destination-port"], 1234)

        def test_host(self):
            """
            The second required command-line argument allows configuring the
            destination host.
            """
            self.options.parseOptions([b"10.0.0.1"])
            self.assertEqual(
                self.options["destination-host"], u"10.0.0.1",
            )

    return Tests


class DatasetAgentOptionsTests(
        make_amp_agent_options_tests(DatasetAgentOptions)
):
    """
    Tests for ``DatasetAgentOptions``.
    """


class ContainerAgentOptionsTests(
        make_amp_agent_options_tests(ContainerAgentOptions)
):
    """
    Tests for ``ContainerAgentOptions``.
    """


class ZFSAgentOptionsTests(make_amp_agent_options_tests(ZFSAgentOptions)):
    """
    Tests for ``ZFSAgentOptions``.
    """


class ZFSAgentOptionsVolumeTests(make_volume_options_tests(
        ZFSAgentOptions, [b"1.2.3.4"])):
    """
    Tests for the volume configuration arguments of ``ZFSAgentOptions``.
    """
