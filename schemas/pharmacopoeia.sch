<?xml version="1.0" encoding="UTF-8"?>
<schema xmlns="http://purl.oclc.org/dsdl/schematron" queryBinding="xslt2">
  <title>pharmacopoeia working-profile schema</title>
  <ns prefix="t" uri="http://www.tei-c.org/ns/1.0"/>
  <ns prefix="xml" uri="http://www.w3.org/XML/1998/namespace"/>

  <pattern id="chapter-structure">
    <title>Chapters must have @n and a head.</title>
    <rule context="t:div[@type='textpart' and @subtype='chapter']">
      <assert test="@n">chapter div must have @n="B.C"</assert>
      <assert test="t:head">chapter div must have a child &lt;head&gt;</assert>
    </rule>
  </pattern>

  <pattern id="note-chains">
    <title>Footnote chains: @next/@prev are reciprocal within the doc.</title>
    <rule context="t:note[@next]">
      <let name="target" value="substring-after(@next, '#')"/>
      <assert test="//t:note[@xml:id=$target]">
        &lt;note@next&gt; targets a non-existent note id
      </assert>
      <assert test="//t:note[@xml:id=$target and @prev]">
        &lt;note@next&gt; target lacks reciprocal @prev
      </assert>
    </rule>
    <rule context="t:note[@prev]">
      <let name="target" value="substring-after(@prev, '#')"/>
      <assert test="//t:note[@xml:id=$target]">
        &lt;note@prev&gt; targets a non-existent note id
      </assert>
    </rule>
  </pattern>

  <pattern id="lemma-corresp-shape">
    <title>@corresp values that start with "lemma:" follow the namespaced shape.</title>
    <rule context="*[starts-with(@corresp, 'lemma:')]">
      <assert test="matches(@corresp, '^lemma:[a-z0-9-]+:[a-z0-9-]+$')">
        @corresp must match lemma:&lt;edition-slug&gt;:&lt;headword-slug&gt;
      </assert>
    </rule>
  </pattern>

  <pattern id="link-shape">
    <title>linkGrp/@from, @to and link/@target are well-formed.</title>
    <rule context="t:linkGrp">
      <assert test="@from and @to">linkGrp must have @from and @to</assert>
    </rule>
    <rule context="t:link[@target]">
      <assert test="contains(@target, ' ')">
        link/@target must contain two whitespace-separated lemma ids
      </assert>
    </rule>
  </pattern>

  <pattern id="lb-standard">
    <title>&lt;lb&gt; outside &lt;note&gt; bodies must have @n.</title>
    <rule context="t:lb[not(ancestor::t:note)]">
      <assert test="@n">&lt;lb&gt; outside &lt;note&gt; must have @n (page-line number)</assert>
    </rule>
    <rule context="t:lb | t:pb">
      <assert test="not(@bbox)">&lt;lb&gt;/&lt;pb&gt; must not carry @bbox (OCR artefact)</assert>
      <assert test="not(@cert)">&lt;lb&gt;/&lt;pb&gt; must not carry @cert (OCR artefact)</assert>
      <assert test="not(@seq)">&lt;lb&gt;/&lt;pb&gt; must not carry @seq</assert>
    </rule>
  </pattern>

  <pattern id="facs-shape">
    <title>@facs must be a renderable image URL — never JPEG 2000.</title>
    <rule context="*[@facs]">
      <assert test="not(ends-with(@facs, '.jp2')) and not(ends-with(@facs, '.jp2/'))">
        @facs must not point at a bare JP2 resource — browsers cannot render
        JPEG 2000. Rewrite to the IIIF JPEG derivative
        (https://iiif.archive.org/.../full/1200,/0/default.jpg) and preserve
        the JP2 URL on @source.
      </assert>
      <assert test="
        starts-with(@facs, 'https://digi.ub.uni-heidelberg.de/') or
        starts-with(@facs, 'https://iiif.archive.org/') or
        starts-with(@facs, 'https://archive.org/') or
        starts-with(@facs, 'https://wellcomecollection.org/') or
        starts-with(@facs, 'page_images/') or
        starts-with(@facs, 'local:')">
        @facs must be a known canonical URL or a local path
      </assert>
    </rule>
  </pattern>
</schema>
