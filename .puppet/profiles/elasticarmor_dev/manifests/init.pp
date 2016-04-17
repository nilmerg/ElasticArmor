# Class: elasticarmor_dev
#
#   This class sets up a development environment for ElasticArmor.
#
# Parameters:
#
# Actions:
#
# Requires:
#
# Sample Usage:
#
#   include elasticarmor_dev
#
class elasticarmor_dev {
    file { '/etc/elasticarmor':
        ensure => directory
    }
    -> file { '/etc/elasticarmor/config.ini':
        notify => Service['elasticarmor'],
        ensure => file,
        source => '/vagrant/.puppet/files/elasticarmor/config.ini'
    }

    file { '/var/log/elasticarmor':
        ensure => directory
    }

    exec { 'config-index':
        require     => Class['elasticsearch'],
        provider    => shell,
        unless      => 'sleep 10 && curl -sf -XHEAD localhost:9200/.elasticarmor',
        command     => 'curl -XPOST localhost:9200/.elasticarmor -d @/vagrant/.puppet/files/elasticarmor/config-index.json'
    }
    -> exec { 'server-role':
        provider    => shell,
        unless      => 'curl -sf -XHEAD localhost:9200/.elasticarmor/role/kibana-server',
        command     => 'curl -XPOST localhost:9200/.elasticarmor/role/kibana-server?refresh -d @/vagrant/.puppet/files/elasticarmor/kibana-server.json'
    }
    -> exec { 'user-role':
        provider    => shell,
        unless      => 'curl -sf -XHEAD localhost:9200/.elasticarmor/role/kibana-user',
        command     => 'curl -XPOST localhost:9200/.elasticarmor/role/kibana-user?refresh -d @/vagrant/.puppet/files/elasticarmor/kibana-user.json'
    }

    package { 'python-ldap': }
    package { 'python-requests': }

    file { '/usr/lib/python2.7/site-packages/elasticarmor':
        ensure => link,
        target => '/vagrant/lib/elasticarmor'
    }
    -> file { '/etc/init.d/elasticarmor':
        ensure => file,
        source => '/vagrant/etc/init.d/elasticarmor'
    }
    -> service { 'elasticarmor':
        require => [ Class['elasticsearch'], Package['python-ldap'], Package['python-requests'] ],
        ensure  => running,
        enable  => true
    }
}