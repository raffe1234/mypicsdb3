# Global search

MyPicsDB 3 version 0.2.19 adds a skin-independent **Search** entry to the add-on
main menu. Search is implemented through Query Model version 1 and works with
both SQLite and MySQL/MariaDB.

## Indexed fields

One normalized search document is maintained for every picture. It contains
bounded tokens from:

- filename;
- embedded caption;
- keywords;
- the picture URI, which supplies folder and path parts;
- camera make and model;
- city, state, country and sublocation.

Lens and arbitrary metadata facets are not stored by the current catalogue and
therefore are not searched yet.

## Token rules

Search and indexing use the same tokenizer:

- Unicode NFKC normalization;
- Unicode `casefold()`;
- letters and numbers are retained, including Swedish å, ä and ö;
- punctuation, underscores, dashes and path separators split words;
- duplicate query words are removed;
- multiple query words use AND semantics;
- a query may contain at most 512 characters and 12 distinct words;
- each word may contain at most 191 characters.

Words may match different fields on the same picture. A query such as
`fujifilm göteborg sommar` can therefore match a camera make, a location and a
keyword. Version 0.2.19 does not promise phrase order, fuzzy matching, stemming,
prefix completion or language-specific morphology.

## Database representation

Schema 3 adds `picture_search_documents`:

```text
picture_id  primary key and foreign key to pictures.id
document    normalized, space-padded token document
```

The scanner replaces the document whenever a picture's searchable metadata is
inserted or updated. The schema-2-to-3 migration backfills all existing picture
rows in batches and includes their current keywords.

A search Query Model rule compiles to a parameterized subquery over the search
document. Search words never become SQL identifiers, operators or literal SQL.
The implementation deliberately does not require SQLite FTS5 or MySQL
FULLTEXT, preserving backend parity and simple migration/recovery behaviour.

## Display policy and pagination

The local **Minimum picture rating** policy applies to search by default, just
as it does to normal browser views. The main-menu **Show all pictures
temporarily** option is propagated into search and its subsequent pages.

Search results use the normal browser page size. The normalized search text and
temporary rating-policy override are retained in **Next page** URLs.

## Performance validation

The normalized document avoids repeatedly scanning all metadata tables and
keeps migration and maintenance backend-neutral. It is still a bounded table
scan rather than a full-text engine. Before declaring large-library search
production-stable, measure warm and cold searches on the target catalogue of
approximately 135,000 pictures for SQLite on the NAS and for MariaDB.

A future, separately migrated accelerator may be added if measurements require
it, but it must remain optional and preserve Query Model semantics.
