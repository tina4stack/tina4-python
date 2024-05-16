create table test (
    id integer default 0 not null,
    first_name varchar(200) default '',
    last_name varchar(200) default '',
    age integer default 0,
    date_created timestamp default null,
    primary key (id)
);