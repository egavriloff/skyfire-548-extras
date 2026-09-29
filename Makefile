.PHONY: module-build module-build-image module-build-list module-build-clean

module-build:
	@if [ -n "$(MODULE)" ]; then \
		sh .ci/module-build/build.sh "$(MODULE)"; \
	else \
		sh .ci/module-build/build.sh all; \
	fi

module-build-image:
	@sh .ci/module-build/build.sh image

module-build-list:
	@sh .ci/module-build/build.sh list

module-build-clean:
	@sh .ci/module-build/build.sh clean
