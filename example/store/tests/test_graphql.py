"""Test GraphQL engine — demonstrates: schema generation from ORM, custom resolvers,
query execution with variables, and field selection.
"""
import pytest
from tina4_python.graphql import GraphQL
from src.orm.product import Product
from src.orm.category import Category


class TestGraphQLSchemaFromORM:
    def test_from_orm_generates_product_type(self, db):
        gql = GraphQL()
        gql.schema.from_orm(Product)

        assert "Product" in gql.schema.types
        fields = gql.schema.types["Product"]
        assert "id" in fields
        assert "name" in fields
        assert "price" in fields

    def test_from_orm_generates_category_type(self, db):
        gql = GraphQL()
        gql.schema.from_orm(Category)

        assert "Category" in gql.schema.types
        fields = gql.schema.types["Category"]
        assert "id" in fields
        assert "name" in fields

    def test_from_orm_creates_single_and_list_queries(self, db):
        gql = GraphQL()
        gql.schema.from_orm(Product)

        assert "product" in gql.schema.queries
        assert "products" in gql.schema.queries

    def test_from_orm_creates_mutations(self, db):
        gql = GraphQL()
        gql.schema.from_orm(Product)

        assert "createProduct" in gql.schema.mutations
        assert "updateProduct" in gql.schema.mutations
        assert "deleteProduct" in gql.schema.mutations

    def test_schema_sdl_output(self, db):
        gql = GraphQL()
        gql.schema.from_orm(Product)
        sdl = gql.schema_sdl()

        assert "type Product" in sdl
        assert "type Query" in sdl


class TestGraphQLExecute:
    def _build_engine(self):
        gql = GraphQL()
        gql.schema.from_orm(Product)
        gql.schema.from_orm(Category)
        return gql

    def test_query_single_product(self, db, sample_product):
        gql = self._build_engine()
        result = gql.execute(
            '{ product(id: "' + str(sample_product.id) + '") { id name price } }'
        )
        assert result["data"]["product"] is not None
        assert result["data"]["product"]["name"] == "Widget Pro"

    def test_query_nonexistent_product(self, db):
        gql = self._build_engine()
        result = gql.execute('{ product(id: "99999") { id name } }')
        assert result["data"]["product"] is None

    def test_query_products_list(self, db, sample_product):
        gql = self._build_engine()
        result = gql.execute("{ products { id name } }")
        assert "data" in result
        assert "products" in result["data"]

    def test_parse_error_returns_errors(self, db):
        gql = self._build_engine()
        result = gql.execute("{ invalid syntax !!!")
        assert "errors" in result
        assert len(result["errors"]) > 0


class TestGraphQLCustomResolvers:
    def _build_engine(self):
        gql = GraphQL()
        gql.schema.from_orm(Product)
        gql.schema.from_orm(Category)

        def search_products(root, args, ctx):
            term = args.get("term", "")
            if not term or len(term) < 2:
                return []
            like = f"%{term}%"
            return [p.to_dict() for p in Product.where(
                "(name like ? or description like ?) and is_active = 1",
                params=[like, like],
                limit=args.get("limit", 10),
            )]

        def products_by_price(root, args, ctx):
            return [p.to_dict() for p in Product.where(
                "price between ? and ? and is_active = 1",
                params=[args.get("min_price", 0), args.get("max_price", 99999)],
                limit=50,
            )]

        gql.schema.add_query(
            "search_products",
            {"term": "String", "limit": "Int"},
            "[Product]",
            search_products,
        )
        gql.schema.add_query(
            "products_by_price",
            {"min_price": "Float", "max_price": "Float"},
            "[Product]",
            products_by_price,
        )
        return gql

    def test_search_products_finds_match(self, db, sample_product):
        gql = self._build_engine()
        result = gql.execute('{ search_products(term: "Widget") { id name } }')
        data = result["data"]["search_products"]
        assert len(data) >= 1
        assert data[0]["name"] == "Widget Pro"

    def test_search_products_short_term(self, db, sample_product):
        gql = self._build_engine()
        result = gql.execute('{ search_products(term: "W") { id } }')
        assert result["data"]["search_products"] == []

    def test_products_by_price_range(self, db, sample_product):
        gql = self._build_engine()
        result = gql.execute(
            "{ products_by_price(min_price: 20.0, max_price: 40.0) { name price } }"
        )
        data = result["data"]["products_by_price"]
        assert len(data) >= 1
        assert data[0]["name"] == "Widget Pro"

    def test_products_by_price_no_match(self, db, sample_product):
        gql = self._build_engine()
        result = gql.execute(
            "{ products_by_price(min_price: 500.0, max_price: 600.0) { name } }"
        )
        assert result["data"]["products_by_price"] == []


class TestGraphQLVariables:
    def test_query_with_variables(self, db, sample_product):
        gql = GraphQL()
        gql.schema.from_orm(Product)

        query = """
            query GetProduct($pid: ID!) {
                product(id: $pid) { id name price }
            }
        """
        result = gql.execute(query, variables={"pid": str(sample_product.id)})
        assert result["data"]["product"]["name"] == "Widget Pro"

    def test_variable_default_value(self, db, sample_product):
        gql = GraphQL()
        gql.schema.from_orm(Product)

        query = """
            query ListProducts($lim: Int = 5) {
                products(limit: $lim) { id name }
            }
        """
        result = gql.execute(query)
        assert "data" in result
        assert "products" in result["data"]
