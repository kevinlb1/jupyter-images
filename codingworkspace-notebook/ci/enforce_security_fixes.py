#!/usr/bin/env python3
"""Reject every reported vulnerability for which the scanner knows a fix."""
import json
from pathlib import Path
import sys


def fixable_findings(report):
    if report.get('SchemaVersion') != 2 or not isinstance(report.get('Results'), list):
        raise ValueError('expected a complete Trivy schema 2 report')
    return [dict(target=result['Target'], package=v['PkgName'], id=v['VulnerabilityID'],
                 severity=v['Severity'], installed=v['InstalledVersion'], fixed=v['FixedVersion'])
            for result in report['Results'] for v in result.get('Vulnerabilities', [])
            if v.get('FixedVersion')]


if __name__ == '__main__':
    findings = fixable_findings(json.loads(Path(sys.argv[1]).read_text()))
    print(json.dumps({'fixableFindings': findings, 'count': len(findings)}, indent=2))
    raise SystemExit(1 if findings else 0)
