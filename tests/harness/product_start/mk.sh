#!/bin/zsh
D=$(cd $(dirname $0); pwd)/$1; mkdir -p $D/src $D/.claude/skills; cd $D; git init -q
echo "# Existing product repo" > README.md; echo "print('hello')" > src/main.py
ln -s "$ENGINE/skills/product-start" .claude/skills/product-start
git add README.md src && git -c user.name=t -c user.email=t@example.com commit -qm init
echo $D
