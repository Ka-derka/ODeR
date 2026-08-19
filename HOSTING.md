# Hosting an ODeR index

A directory operator can publish one full `.oder` package so visitors can load the complete offline index without crawling every folder. The package is an ordinary static file and can be served from the directory itself, another path, or a CDN.

## Create the package

1. Add and index the directory in ODeR.
2. Choose **Export .oder** for the site.
3. Select **Include cached index**.
4. Publish the resulting file without modifying its contents.

The exported package base URL must exactly match the directory base URL, including any path prefix. A definition-only package cannot be used as a hosted index.

Replace published packages atomically when possible: upload the new file under a temporary name, then rename it over the previous file. This prevents clients from receiving a partially uploaded ZIP.

## Automatic root discovery

The simplest setup is to publish the package at one of these locations beneath the directory base URL:

```text
index.oder
directory.oder
.well-known/oder.oder
```

For a directory at `https://downloads.example.com/archive/`, the preferred URL is:

```text
https://downloads.example.com/archive/index.oder
```

## Advertise a package stored elsewhere

Add a link element to the directory HTML when the package is on another path or host:

```html
<link
  rel="oder-index"
  type="application/vnd.oder+zip"
  href="https://cdn.example.com/archive/latest.oder">
```

An ordinary anchor ending in `.oder` is also discoverable, but the explicit relationship is recommended because it clearly identifies the canonical index.

Servers can advertise the same package through an HTTP response header:

```http
Link: <https://cdn.example.com/archive/latest.oder>; rel="oder-index"; type="application/vnd.oder+zip"
```

Users can always enter an exact package URL in **Add Site** or **Edit Site**, which works even when the directory page cannot be changed.

## Recommended HTTP behavior

Serve `.oder` files with this media type:

```text
application/vnd.oder+zip
```

Enable `ETag` or `Last-Modified` headers. ODeR stores these values after a successful load and sends `If-None-Match` or `If-Modified-Since` on later updates. A `304 Not Modified` response lets ODeR finish immediately without downloading the package or crawling the directory.

Example nginx configuration:

```nginx
location /archive/ {
    autoindex on;
    add_header Link '</indexes/archive.oder>; rel="oder-index"; type="application/vnd.oder+zip"' always;
}

location = /indexes/archive.oder {
    types { application/vnd.oder+zip oder; }
    etag on;
    try_files $uri =404;
}
```

## Validation and fallback

Before changing the local cache, ODeR verifies:

- the ZIP layout and supported format version;
- manifest and profile metadata;
- declared and actual file sizes;
- SHA-256 checksums;
- SQLite integrity, schema, and cache counts;
- that the package contains a full cached index;
- that its base URL exactly matches the configured directory.

The package is streamed to temporary storage and is not imported as a new site. Only its index contents are applied, so the user's local site name, network limits, download settings, favorites, and crawl history remain intact.

If no valid hosted package is available, ODeR falls back to its existing JSON, sitemap, or HTML directory discovery. Failed candidates are recorded in Logs without replacing a working cache.
