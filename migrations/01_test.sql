create table if not exists test_user (    date_created timestamp,
                            email varchar(255) default 'test@test.com',
                            first_name varchar(255) default '',
                            id integer default 1  not null,
                            last_name varchar(255) default '',
                            title varchar(255) default 'Mr',
                            moo jsonb,
                            balance numeric (10,2) default 10.00,
                            age integer default 64,
                            primary key (id)
);
create table test_user_item (       date_created timestamp,
                                    id integer default 1  not null,
                                    name varchar(255) default 'Item 1',
                                    user_id integer references test_user(id) on update cascade on delete cascade,
                                    primary key (id)
);