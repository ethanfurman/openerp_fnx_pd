{
    'name': 'Fnx Production',
    'version': '0.1',
    'category': 'Generic Modules',
    'description': """\
            Phoenix Production Orders.

            Keeps track of production orders.
            """,
    'author': 'Emile van Sebille',
    'maintainer': 'Emile van Sebille',
    'website': 'www.openerp.com',
    'depends': [
            'base',
            'cmms',
            'crm',
            'fis_integration',
            'fnx',
            'product',
        ],
    'data': [
            'security/fnxpd_security.xaml',
            'security/ir.model.access.csv',
            'product_view.xaml',
            'production_view.xaml',
        ],
    'test': [],
    'installable': True,
    'active': False,
}
