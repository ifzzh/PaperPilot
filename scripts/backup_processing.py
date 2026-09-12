#!/usr/bin/env python3
"""Consistent iPaper DB + immutable structure artifacts backup; no credentials output."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ipaper.processing.maintenance import backup

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--database',required=True)
    parser.add_argument('--papers-root',required=True)
    parser.add_argument('--destination',required=True)
    args=parser.parse_args()
    print(json.dumps(backup(args.database,args.papers_root,args.destination),ensure_ascii=False))
