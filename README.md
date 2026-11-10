### CHANGE AN LDAP PASSWORD

<!-- (openldap-jml) chris@LAPTOP-BQ2HJ273:~/python/openldap-jml$ slappasswd
New password:
Re-enter new password:
<PASSWORD HASH>
(openldap-jml) chris@LAPTOP-BQ2HJ273:~/python/openldap-jml$ cat << 'EOF' > change-password.ldif
dn: olcDatabase={1}mdb,cn=config
changetype: modify
replace: olcRootPW
olcRootPW: <PASSWORD HASH>
EOF
(openldap-jml) chris@LAPTOP-BQ2HJ273:~/python/openldap-jml$ sudo ldapmodify -H ldapi:// -Y EXTERNAL -f change-password.ldif
SASL/EXTERNAL authentication started
SASL username: gidNumber=0+uidNumber=0,cn=peercred,cn=external,cn=auth
SASL SSF: 0
modifying entry "olcDatabase={1}mdb,cn=config"

(openldap-jml) chris@LAPTOP-BQ2HJ273:~/python/openldap-jml$ ldapwhoami -H ldap://localhost -D "cn=admin,dc=neuropunk" -W
Enter LDAP Password:
dn:cn=admin,dc=neuropunk -->


## RUNNING FASTAPI
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

## NGROK

ngrok http 8000 --url welcome-capital-jaybird.ngrok-free.app