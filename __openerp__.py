{
    'name': 'Fnx Production',
    'version': '0.2',
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
            'fis_integration',
            'fnx',
            'product',
        ],
    'data': [
            'security/fnxpd_security.xaml',
            'security/ir.model.access.csv',
            'production_data.xaml',
            'product_view.xaml',
            'production_view.xaml',
        ],
    'test': [],
    'installable': True,
    'active': False,
}
